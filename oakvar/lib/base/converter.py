from typing import Optional
from typing import Any
from typing import Union
from typing import Tuple
from typing import List
from typing import Dict
from typing import TextIO
from io import BufferedReader
import polars as pl
from pyliftover import LiftOver


class BaseConverter(object):
    IGNORE = "converter_ignore"

    def __init__(
        self,
        inputs: List[str] = [],
        input_format: Optional[str] = None,
        name: Optional[str] = None,
        output_dir: Optional[str] = None,
        genome: Optional[str] = None,
        serveradmindb=None,
        module_options: Dict = {},
        input_encoding=None,
        outer=None,
        title: Optional[str] = None,
        conf: Dict[str, Any] = {},
        code_version: Optional[str] = None,
        run_name: Optional[str] = None,
        ignore_sample: bool=False,
    ):
        from re import compile
        from pathlib import Path
        import inspect
        from oakvar import get_wgs_reader
        from oakvar.lib.exceptions import ExpectedException
        from oakvar.lib.module.local import get_module_conf

        self.logger = None
        self.crv_writer = None
        self.crs_writer = None
        self.crm_writer = None
        self.crl_writer = None
        self.converters = {}
        self.available_input_formats: List[str] = []
        self.input_dir = None
        self.input_path_dict = {}
        self.input_path_dict2 = {}
        self.input_file_handles: Dict[str, Union[TextIO, BufferedReader]] = {}
        self.output_base_fname: Optional[str] = None
        self.error_logger = None
        self.unique_excs: Dict[str, int] = {}
        self.err_holder = []
        self.wpath = None
        self.crm_path = None
        self.crs_path = None
        self.crl_path = None
        self.do_liftover = None
        self.do_liftover_chrM = None
        self.uid: int = 0
        self.read_lnum: int = 0
        self.lifter = None
        self.module_options = None
        self.given_input_assembly: Optional[str] = genome
        self.converter_by_input_path: Dict[str, Optional[BaseConverter]] = {}
        self.file_num_valid_variants = 0
        self.file_error_lines = 0
        self.total_num_valid_variants = 0
        self.total_error_lines = 0
        self.fileno = 0
        self.extra_output_columns: List[Dict[str, Any]] = []
        self.total_num_converted_variants = 0
        self.input_formats: List[str] = []
        self.genome_assemblies: List[str] = []
        self.base_re = compile("^[ATGC]+|[-]+$")
        self.chromdict = {
            "chrx": "chrX",
            "chry": "chrY",
            "chrMT": "chrM",
            "chrMt": "chrM",
            "chr23": "chrX",
            "chr24": "chrY",
        }
        if not inputs:
            raise ExpectedException("Input files are not given.")
        self.input_paths = inputs
        self.format = input_format
        self.script_path = Path(inspect.getfile(self.__class__))
        self.ignore_sample: bool = ignore_sample
        self.header_num_line: int = 0
        self.line_no: int = 0
        if name:
            self.name: str = name
        else:
            self.name = self.script_path.stem.split("-")[0]
        self.output_dir = output_dir
        self.parse_inputs()
        self.parse_output_dir()
        self.conf: Dict[str, Any] = (
            get_module_conf(self.name, module_type="converter") or {}
        )
        if conf:
            self.conf.update(conf.copy())
        self.module_options = module_options
        self.serveradmindb = serveradmindb
        self.input_encoding = input_encoding
        self.outer = outer
        self.setup_logger()
        self.wgs_reader = get_wgs_reader(assembly="hg38")
        self.time_error_written: float = 0

        self.module_type = "converter"
        self.format_name: str = ""
        self.run_name = run_name
        self.input_path = ""
        self.total_num_converted_variants = 0
        self.title = title
        if self.title:
            self.conf["title"] = self.title
        elif "title" in self.conf:
            self.title = self.conf["title"]
        self.version: str = ""
        if code_version:
            self.code_version = code_version
        else:
            if "code_version" in self.conf:
                self.code_version: str = self.conf["version"]
            elif "version" in self.conf:
                self.code_version: str = self.conf["version"]
            else:
                self.code_version: str = ""
        self.collect_input_file_handles()
        self.collect_extra_output_columns()

    def check_format(self, *__args__, **__kwargs__):
        pass

    def get_variant_lines(
        self, input_path: str, mp: int, start_line_no: int, batch_size: int
    ) -> Tuple[Dict[int, List[Tuple[int, Any]]], bool]:
        import linecache

        immature_exit: bool = False
        line_no: int = start_line_no
        end_line_no = line_no + mp * batch_size - 1
        lines: Dict[int, List[Tuple[int, Any]]] = {i: [] for i in range(mp)}
        chunk_no: int = 0
        chunk_size: int = 0
        while True:
            line = linecache.getline(input_path, line_no)
            if not line:
                break
            line = line[:-1]
            lines[chunk_no].append((line_no, line))
            chunk_size += 1
            if line_no >= end_line_no:
                immature_exit = True
                break
            line_no += 1
            if chunk_size >= batch_size:
                chunk_no += 1
                chunk_size = 0
        return lines, immature_exit

    def prepare_for_mp(self):
        pass

    def write_extra_info(self, _: dict):
        pass

    def convert_line(self, *__args__, **__kwargs__) -> List[Dict[str, Any]]:
        return []

    def addl_operation_for_unique_variant(self, __wdict__, __wdict_no__):
        pass

    def save(self, overwrite: bool = False, interactive: bool = False):
        from ..module.local import create_module_files

        create_module_files(self, overwrite=overwrite, interactive=interactive)

    def get_do_liftover_chrM(self, genome_assembly, f, do_liftover):
        _ = genome_assembly or f
        return do_liftover

    def set_do_liftover(self, genome_assembly, f):
        self.do_liftover = genome_assembly != "hg38"
        self.do_liftover_chrM = self.get_do_liftover_chrM(
            genome_assembly, f, self.do_liftover
        )
        if self.logger:
            self.logger.info(f"liftover needed: {self.do_liftover}")
            self.logger.info(f"liftover for chrM needed: {self.do_liftover_chrM}")

    def setup_lifter(self, genome_assembly) -> Optional[LiftOver]:
        from oakvar.lib.util.seq import get_lifter

        self.lifter = get_lifter(source_assembly=genome_assembly)

    def parse_inputs(self):
        from pathlib import Path

        self.input_paths = [str(Path(x).resolve()) for x in self.input_paths if x != "-"]
        self.input_dir = str(Path(self.input_paths[0]).parent)
        for i in range(len(self.input_paths)):
            self.input_path_dict[i] = self.input_paths[i]
            self.input_path_dict2[self.input_paths[i]] = i

    def parse_output_dir(self):
        from pathlib import Path
        from os import makedirs

        if not self.output_dir:
            self.output_dir = self.input_dir
        if not self.output_dir:
            raise
        if not (Path(self.output_dir).exists()):
            makedirs(self.output_dir)
        self.output_base_fname: Optional[str] = self.name
        if not self.output_base_fname:
            if not self.input_paths:
                raise
            self.output_base_fname = Path(self.input_paths[0]).name

    def get_file_object_for_input_path(self, input_path: str):
        import gzip
        from pathlib import Path
        from oakvar.lib.util.util import detect_encoding

        suffix = Path(input_path).suffix
        # TODO: Remove the hardcoding.
        if suffix in [".parquet"]:
            encoding = None
        else:
            if self.input_encoding:
                encoding = self.input_encoding
            else:
                if self.logger:
                    self.logger.info(f"detecting encoding of {input_path}")
                encoding = detect_encoding(input_path)
        if self.logger:
            self.logger.info(f"encoding: {input_path} {encoding}")
        if input_path.endswith(".gz"):
            f = gzip.open(input_path, mode="rt", encoding=encoding)
        elif suffix in [".parquet"]:
            f = open(input_path, "rb")
        else:
            f = open(input_path, encoding=encoding)
        return f

    def setup_logger(self):
        from logging import getLogger

        self.logger = getLogger("oakvar.converter")
        self.error_logger = getLogger("err.converter")

    def log_input_and_genome_assembly(self, input_path, genome_assembly):
        if not self.logger:
            return
        self.logger.info(f"input file: {input_path}")
        self.logger.info(f"input format: {self.format_name}")
        self.logger.info(f"genome_assembly: {genome_assembly}")

    def collect_input_file_handles(self):
        for input_path in self.input_paths:
            f = self.get_file_object_for_input_path(input_path)
            self.input_file_handles[input_path] = f

    def setup(self, _):
        raise NotImplementedError("setup method should be implemented.")

    def setup_file(self, input_path: str) -> Union[TextIO, BufferedReader]:
        from oakvar.lib.util.util import log_module

        f = self.input_file_handles[input_path]
        log_module(self, self.logger)
        self.input_path = input_path
        self.setup(f)
        genome_assembly = self.get_genome_assembly()
        self.genome_assemblies.append(genome_assembly)
        self.log_input_and_genome_assembly(input_path, genome_assembly)
        self.set_do_liftover(genome_assembly, f)
        if self.do_liftover or self.do_liftover_chrM:
            self.setup_lifter(genome_assembly)
        f.seek(0)
        return f

    def get_genome_assembly(self) -> str:
        from oakvar.lib.system.consts import default_assembly_key
        from oakvar.lib.exceptions import NoGenomeException
        from oakvar.lib.system import get_user_conf

        if self.given_input_assembly:
            return self.given_input_assembly
        input_assembly = getattr(self, "input_assembly", None)
        if input_assembly:
            return input_assembly
        user_conf = get_user_conf() or {}
        genome_assembly = user_conf.get(default_assembly_key, None)
        if genome_assembly:
            return genome_assembly
        raise NoGenomeException()

    def handle_chrom(self, variant):
        from oakvar.lib.exceptions import IgnoredVariant

        if not variant.get("chrom"):
            raise IgnoredVariant("No chromosome")
        if not variant.get("chrom").startswith("chr"):
            variant["chrom"] = "chr" + variant.get("chrom")
        variant["chrom"] = self.chromdict.get(
            variant.get("chrom"), variant.get("chrom")
        )

    def handle_ref_base(self, variant):
        from oakvar.lib.exceptions import IgnoredVariant

        if "ref_base" not in variant or variant["ref_base"] in [
            "",
            ".",
        ]:
            if not self.wgs_reader:
                raise
            variant["ref_base"] = self.wgs_reader.get_bases( # type: ignore
                variant.get("chrom"), int(variant["pos"])
            ).upper()
        else:
            ref_base = variant["ref_base"]
            if ref_base == "" and variant["alt_base"] not in [
                "A",
                "T",
                "C",
                "G",
            ]:
                raise IgnoredVariant("Reference base required for non SNV")
            elif ref_base is None or ref_base == "":
                if not self.wgs_reader:
                    raise
                variant["ref_base"] = self.wgs_reader.get_bases( # type: ignore
                    variant.get("chrom"), int(variant.get("pos"))
                )

    def handle_genotype(self, variant):
        if "genotype" in variant and "." in variant["genotype"]:
            variant["genotype"] = variant["genotype"].replace(".", variant["ref_base"])

    def check_invalid_base(self, variant: dict):
        from oakvar.lib.exceptions import IgnoredVariant

        if not self.base_re.fullmatch(variant["ref_base"]):
            raise IgnoredVariant("Invalid reference base")
        if not self.base_re.fullmatch(variant["alt_base"]):
            raise IgnoredVariant("Invalid alternate base")

    def normalize_variant(self, variant):
        from oakvar.lib.util.seq import normalize_variant_left

        p, r, a = (
            int(variant["pos"]),
            variant["ref_base"],
            variant["alt_base"],
        )
        (
            new_pos,
            new_ref,
            new_alt,
        ) = normalize_variant_left("+", p, r, a)
        variant["pos"] = new_pos
        variant["ref_base"] = new_ref
        variant["alt_base"] = new_alt

    def add_unique_variant(self, variant: dict, unique_variants: set):
        var_str = (
            f"{variant['chrom']}:{variant['pos']}:{variant['ref_base']}"
            + f":{variant['alt_base']}"
        )
        is_unique = var_str not in unique_variants
        if is_unique:
            unique_variants.add(var_str)
        return is_unique

    def add_end_pos_if_absent(self, variant: dict):
        col_name = "pos_end"
        if col_name not in variant:
            ref_base = variant["ref_base"]
            ref_len = len(ref_base)
            if ref_len == 1:
                variant[col_name] = variant["pos"]
            else:
                variant[col_name] = variant["pos"] + ref_len - 1

    def gather_variantss_wrapper(self, args):
        return self.gather_variantss(*args)

    def gather_variantss(self,
            lines_data: Dict[int, List[Tuple[int, Dict[str, Any]]]],
            core_num: int, 
            do_liftover: bool, 
            do_liftover_chrM: bool, 
            lifter, 
            wgs_reader, 
            logger, 
            error_logger, 
            input_path: str, 
            input_fname: str, 
            unique_excs: dict, 
            err_holder: list,
            num_valid_error_lines: Dict[str, int],
    ) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
        variants_l = []
        crl_l = []
        line_data = lines_data[core_num]
        for (line_no, line) in line_data:
            try:
                variants = self.convert_line(line)
                variants_datas, crl_datas = self.handle_converted_variants(variants, do_liftover, do_liftover_chrM, lifter, wgs_reader, logger, error_logger, input_path, input_fname, unique_excs, err_holder, line_no, num_valid_error_lines)
                if variants_datas is None or crl_datas is None:
                    continue
                variants_l.append(variants_datas)
                crl_l.append(crl_datas)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self._log_conversion_error(line_no, e)
                num_valid_error_lines["error"] += 1
        return variants_l, crl_l

    def is_unique_variant(self, variant: dict, unique_vars: dict) -> bool:
        return variant["var_no"] not in unique_vars

    def handle_converted_variants(self,
            variants: List[Dict[str, Any]], do_liftover: bool, do_liftover_chrM: bool, lifter, wgs_reader, logger, error_logger, input_path: str, input_fname: str, unique_excs: dict, err_holder: list, line_no: int, num_valid_error_lines: Dict[str, int]
    ):
        from oakvar.lib.exceptions import IgnoredVariant

        if variants is BaseConverter.IGNORE:
            return None, None
        if not variants:
            raise IgnoredVariant("No valid alternate allele was found in any samples.")
        unique_vars = {}
        variant_l: List[Dict[str, Any]] = []
        crl_l: List[Dict[str, Any]] = []
        for variant in variants:
            try:
                crl_data = self.handle_variant(variant, unique_vars, do_liftover, do_liftover_chrM, lifter, wgs_reader, line_no, num_valid_error_lines)
            except Exception as e:
                self._log_conversion_error(line_no, e)
                continue
            variant_l.append(variant)
            if crl_data:
                crl_l.append(crl_data)
        return variant_l, crl_l

    def handle_variant(
        self,
        variant: dict, unique_vars: dict, do_liftover: bool, do_liftover_chrM: bool, lifter, wgs_reader, line_no: int, num_valid_error_lines: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        from oakvar.lib.exceptions import NoVariantError

        if variant["ref_base"] == variant["alt_base"]:
            raise NoVariantError()
        tags = variant.get("tags")
        unique = self.is_unique_variant(variant, unique_vars)
        if unique:
            variant["unique"] = True
            unique_vars[variant["var_no"]] = True
            self.handle_chrom(variant)
            self.handle_ref_base(variant)
            self.check_invalid_base(variant)
            self.normalize_variant(variant)
            self.add_end_pos_if_absent(variant)
            crl_data = self.perform_liftover_if_needed(variant)
            num_valid_error_lines["valid"] += 1
        else:
            variant["unique"] = False
            crl_data = None
        self.handle_genotype(variant)
        if unique:
            variant["original_line"] = line_no
            variant["tags"] = tags
        return crl_data

    def get_df(self, input_path: str, line_no: int=0, file_pos: int=0, ignore_sample: bool=False):
        from pathlib import Path

        input_fname = Path(input_path).name
        f = self.setup_file(self.input_path)
        for self.read_lnum, variants in self.convert_file(
            f, input_path=input_path, line_no=line_no, file_pos=file_pos, exc_handler=self._log_conversion_error, ignore_sample=ignore_sample
        ):
            num_handled_variant: int = 0
            try:
                num_handled_variant = self.handle_converted_variants(variants, var_ld)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self._log_conversion_error(self.read_lnum, e)
            len_variants: int = num_handled_variant
            len_chunk += len_variants
            len_df += len_variants
            if len_chunk >= chunk_size:
                df = self.get_df_from_var_ld(var_ld)
                if total_df is None:
                    total_df = df
                else:
                    total_df.extend(df)
                self.initialize_var_ld(var_ld)
                len_chunk = 0
            if df_size > 0 and len_df >= df_size:
                total_dfs[df_no] = total_df
                df_no += 1
                if df_no == list_size:
                    yield total_dfs
                    total_dfs = [None] * list_size
                    df_no = 0
                total_df = None
                len_df = 0
            if self.read_lnum % 10000 == 0:
                status = (
                    f"Running Converter ({self.input_fname}): line {self.read_lnum}"
                )
                update_status(
                    status, logger=self.logger, serveradmindb=self.serveradmindb
                )
        if len_chunk:
            df = self.get_df_from_var_ld(var_ld)
            if total_df is None:
                total_df = df
            else:
                total_df.extend(df)
            self.initialize_var_ld(var_ld)
            len_chunk = 0
            total_dfs[df_no] = total_df
            yield total_dfs
            total_df = None
            len_df = 0
            df_no = 0

    def collect_extra_output_columns(self):
        extra_output_columns = self.conf.get("extra_output_columns")
        if not extra_output_columns:
            return
        for col in extra_output_columns:
            self.extra_output_columns.append(col)

    def run(self):
        from pathlib import Path
        from multiprocessing.pool import ThreadPool
        #import time
        from oakvar.lib.util.run import update_status

        if not self.input_paths or not self.logger:
            raise
        update_status(
            "started converter", logger=self.logger, serveradmindb=self.serveradmindb
        )
        self.set_variables_pre_run()
        if not self.crv_writer:
            raise ValueError("No crv_writer")
        if not self.crs_writer:
            raise ValueError("No crs_writer")
        if not self.crm_writer:
            raise ValueError("No crm_writer")
        if not self.crl_writer:
            raise ValueError("No crl_writer")
        batch_size: int = 2500
        uid = 1
        num_pool = 4
        pool = ThreadPool(num_pool)
        for input_path in self.input_paths:
            self.input_fname = Path(input_path).name
            fileno = self.input_path_dict2[input_path]
            converter = self.setup_file(input_path)
            self.file_num_valid_variants = 0
            self.file_error_lines = 0
            self.num_valid_error_lines = {"valid": 0, "error": 0}
            start_line_pos: int = 1
            start_line_no: int = start_line_pos
            round_no: int = 0
            #stime = time.time()
            while True:
                #ctime = time.time()
                lines_data, immature_exit = converter.get_variant_lines(input_path, num_pool, start_line_no, batch_size)
                args = [
                    (
                        converter, 
                        lines_data,
                        core_num, 
                        self.do_liftover, 
                        self.do_liftover_chrM, 
                        self.lifter, 
                        self.wgs_reader, 
                        self.logger, 
                        self.error_logger, 
                        input_path, 
                        self.input_fname, 
                        self.unique_excs, 
                        self.err_holder,
                        self.num_valid_error_lines,
                    ) for core_num in range(num_pool)
                ]
                results = pool.map(gather_variantss_wrapper, args)
                lines_data = None
                for result in results:
                    variants_l, crl_l = result
                    for i in range(len(variants_l)):
                        variants = variants_l[i]
                        crl_data = crl_l[i]
                        if len(variants) == 0:
                            continue
                        for variant in variants:
                            variant["uid"] = uid + variant["var_no"]
                            if variant["unique"]:
                                self.crv_writer.write_data(variant)
                                variant["fileno"] = fileno
                                self.crm_writer.write_data(variant)
                                converter.write_extra_info(variant)
                            self.crs_writer.write_data(variant)
                        for crl in crl_data:
                            self.crl_writer.write_data(crl)
                        uid += max([v["var_no"] for v in variants]) + 1
                    variants_l = None
                    crl_l = None
                if not immature_exit:
                    break
                start_line_no += batch_size * num_pool
                round_no += 1
                status = (
                    f"Running Converter ({self.input_fname}): line {start_line_no - 1}"
                )
                update_status(
                    status, logger=self.logger, serveradmindb=self.serveradmindb
                )
            self.logger.info(
                f"{input_path}: number of valid variants: {self.num_valid_error_lines['valid']}"
            )
            self.logger.info(f"{input_path}: number of lines skipped due to errors: {self.num_valid_error_lines['error']}")
            self.total_num_converted_variants += self.num_valid_error_lines["valid"]
            self.total_num_valid_variants += self.num_valid_error_lines["valid"]
            self.total_error_lines += self.num_valid_error_lines["error"]
        flush_err_holder(self.err_holder, self.error_logger, force=True)
        self.close_output_files()
        self.end()
        self.log_ending()
        ret = {
            "total_lnum": self.total_num_converted_variants,
            "write_lnum": self.total_num_valid_variants,
            "error_lnum": self.total_error_lines,
            "input_format": self.input_formats,
            "assemblies": self.genome_assemblies,
        }
        return ret

    def run_df(self, input_path: str="", chunk_size: int=1000, start: int=0, df_size: int = 0, ignore_sample: bool=False):
        from pathlib import Path
        from oakvar.lib.util.run import update_status

        if not self.input_paths or not self.logger:
            raise
        update_status(
            "started converter", logger=self.logger, serveradmindb=self.serveradmindb
        )
        self.collect_input_file_handles()
        self.set_variables_pre_run()
        if df_size > 0 and chunk_size > df_size:
            chunk_size = df_size
        total_df: Optional[pl.DataFrame] = None
        len_df: int = 0
        for self.input_path in self.input_paths:
            self.input_fname = Path(self.input_path).name
            f = self.setup_file(self.input_path)
            self.file_num_valid_variants = 0
            self.file_error_lines = 0
            var_ld: Dict[str, List[Any]] = {}
            self.initialize_var_ld(var_ld)
            len_chunk: int = 0
            total_dfs: List[Optional[pl.DataFrame]] = [None] * list_size
            df_no = 0
            pool = Pool(list_size)
            for self.read_lnum, variants in self.convert_file(
                f, input_path=self.input_path, exc_handler=self._log_conversion_error, ignore_sample=ignore_sample
            ):
                num_handled_variant: int = 0
                try:
                    num_handled_variant = self.handle_converted_variants(variants, var_ld)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._log_conversion_error(self.read_lnum, e)
                len_variants: int = num_handled_variant
                len_chunk += len_variants
                len_df += len_variants
                if len_chunk >= chunk_size:
                    df = self.get_df_from_var_ld(var_ld)
                    if total_df is None:
                        total_df = df
                    else:
                        total_df.extend(df)
                    self.initialize_var_ld(var_ld)
                    len_chunk = 0
                if df_size > 0 and len_df >= df_size:
                    total_dfs[df_no] = total_df
                    df_no += 1
                    if df_no == list_size:
                        yield total_dfs
                        total_dfs = [None] * list_size
                        df_no = 0
                    total_df = None
                    len_df = 0
                if self.read_lnum % 10000 == 0:
                    status = (
                        f"Running Converter ({self.input_fname}): line {self.read_lnum}"
                    )
                    update_status(
                        status, logger=self.logger, serveradmindb=self.serveradmindb
                    )
            if len_chunk:
                df = self.get_df_from_var_ld(var_ld)
                if total_df is None:
                    total_df = df
                else:
                    total_df.extend(df)
                self.initialize_var_ld(var_ld)
                len_chunk = 0
                total_dfs[df_no] = total_df
                yield total_dfs
                total_df = None
                len_df = 0
                df_no = 0
            f.close()
            self.logger.info(
                f"number of valid variants: {self.file_num_valid_variants}"
            )
            self.logger.info(f"number of error lines: {self.file_error_lines}")
        self.close_output_files()
        self.end()
        self.log_ending()
        ret = {
            "total_lnum": self.total_num_converted_variants,
            "write_lnum": self.total_num_valid_variants,
            "error_lnum": self.total_error_lines,
            "input_format": self.input_formats,
            "assemblies": self.genome_assemblies,
        }
        return ret

    def initialize_var_ld(self, var_ld):
        var_ld["base__uid"] = []
        var_ld["base__chrom"] = []
        var_ld["base__pos"] = []
        var_ld["base__ref_base"] = []
        var_ld["base__alt_base"] = []

    def get_df_from_var_ld(self, var_ld: Dict[str, List[Any]]) -> pl.DataFrame:
        df: pl.DataFrame = pl.DataFrame(
            [
                pl.Series("uid", var_ld["base__uid"]),
                pl.Series("chrom", var_ld["base__chrom"]),
                pl.Series("pos", var_ld["base__pos"]),
                pl.Series("ref_base", var_ld["base__ref_base"]),
                pl.Series("alt_base", var_ld["base__alt_base"]),
            ]
        )
        return df

    def set_variables_pre_run(self):
        from time import time

        self.start_time = time()
        self.total_num_converted_variants = 0
        self.uid = 1

    def log_ending(self):
        from time import time, asctime, localtime
        from oakvar.lib.util.run import update_status

        if not self.logger:
            raise
        self.logger.info(
            "total number of converted variants: {}".format(
                self.total_num_converted_variants
            )
        )
        self.logger.info("number of total error lines: %d" % self.total_error_lines)
        end_time = time()
        self.logger.info("finished: %s" % asctime(localtime(end_time)))
        runtime = round(end_time - self.start_time, 3)
        self.logger.info("runtime: %s" % runtime)
        status = "finished Converter"
        update_status(status, logger=self.logger, serveradmindb=self.serveradmindb)

    def perform_liftover_if_needed(self, variant):
        from copy import copy
        from oakvar.lib.util.seq import liftover_one_pos
        from oakvar.lib.util.seq import liftover

        if self.is_chrM(variant):
            needed = self.do_liftover_chrM
        else:
            needed = self.do_liftover
        if needed:
            prelift_wdict = copy(variant)
            crl_data = prelift_wdict
            (
                variant["chrom"],
                variant["pos"],
                variant["ref_base"],
                variant["alt_base"],
            ) = liftover(
                variant["chrom"],
                int(variant["pos"]),
                variant["ref_base"],
                variant["alt_base"],
                lifter=self.lifter,
                wgs_reader=self.wgs_reader,
            )
            converted_end = liftover_one_pos(
                variant["chrom"], variant["pos_end"], lifter=self.lifter
            )
            if converted_end is None:
                pos_end = ""
            else:
                pos_end = converted_end[1]
            variant["pos_end"] = pos_end
        else:
            crl_data = None
        return crl_data

    def is_chrM(self, wdict):
        return wdict["chrom"] == "chrM"

    def flush_err_holder(self, err_holder: list, force: bool=False):
        if len(err_holder) > 1000 or force:
            if self.error_logger:
                for err_line in err_holder:
                    self.error_logger.error(err_line)
            err_holder.clear()

    def _log_conversion_error(self, line_no: int, e):
        from traceback import format_exc
        from oakvar.lib.exceptions import ExpectedException
        from oakvar.lib.exceptions import NoAlternateAllele

        if isinstance(e, NoAlternateAllele):
            return
        if isinstance(e, ExpectedException):
            err_str = str(e)
        else:
            err_str = format_exc().rstrip()
        if err_str not in self.unique_excs:
            err_no = len(self.unique_excs)
            self.unique_excs[err_str] = err_no
            if self.logger:
                self.logger.error(f"Error [{err_no}]: {self.input_path}: {err_str}")
            self.err_holder.append(f"{err_no}:{line_no}\t{str(e)}")
        else:
            err_no = self.unique_excs[err_str]
            self.err_holder.append(f"{err_no}:{line_no}\t{str(e)}")
        self.flush_err_holder(self.err_holder)

    def close_output_files(self):
        if self.crv_writer is not None:
            self.crv_writer.close()
        if self.crm_writer is not None:
            self.crm_writer.close()
        if self.crs_writer is not None:
            self.crs_writer.close()

    def end(self):
        pass
