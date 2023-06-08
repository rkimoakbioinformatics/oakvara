from typing import Any
from typing import Optional
from typing import Union
from typing import Dict
from typing import List
from pathlib import Path
import polars as pl
from ..util.inout import ColumnDefinition


class BaseReporter:
    def __init__(
        self,
        dbpath: str="",
        report_types: List[str] = [],
        filterpath: Optional[str] = None,
        filter=None,
        filtersql: Optional[str] = None,
        filtername: Optional[str] = None,
        filterstring: Optional[str] = None,
        savepath: Optional[Path] = None,
        confpath: Optional[str] = None,
        name: Optional[str] = None,
        nogenelevelonvariantlevel: bool = False,
        separatesample: bool = False,
        output_dir: Optional[str] = None,
        run_name: str = "",
        module_options: Dict = {},
        includesample: Optional[List[str]] = [],
        excludesample: Optional[List[str]] = None,
        package: Optional[str] = None,
        cols: Optional[List[str]] = None,
        level: Optional[str] = None,
        user: Optional[str] = None,
        module_conf: Dict[str, Any] = {},
        no_summary: bool = False,
        logtofile: bool = False,
        df_mode: bool = False,
        use_duckdb: bool = False,
        serveradmindb=None,
        outer=None,
    ):
        import sys
        import os
        from ..system.consts import DEFAULT_SERVER_DEFAULT_USERNAME
        from ..exceptions import ModuleLoadingError
        from ..module.local import get_module_conf

        self.module_type = "annotator"
        self.script_path: str = ""
        self.dbpath = dbpath
        self.report_types = report_types
        self.filterpath = filterpath
        self.filter = filter
        self.filtersql = filtersql
        self.filtername = filtername
        self.filterstring = filterstring
        self.savepath = savepath
        self.confpath = confpath
        self.module_name = name
        self.nogenelevelonvariantlevel = nogenelevelonvariantlevel
        self.separatesample = separatesample
        self.output_dir = output_dir
        self.run_name = run_name
        self.module_options = module_options
        self.includesample = includesample
        self.excludesample = excludesample
        self.package = package
        self.cols = cols
        self.level = level
        self.use_duckdb = use_duckdb
        if dbpath.endswith(".duckdb"):
            self.use_duckdb = True
        if user:
            self.user = user
        else:
            self.user = DEFAULT_SERVER_DEFAULT_USERNAME
        self.no_summary = no_summary
        self.serveradmindb = serveradmindb
        self.outer = outer
        self.cf = None
        self.colinfo = {}
        self.colnos = {}
        self.var_added_cols = []
        self.summarizing_modules = []
        self.columngroups = {}
        self.column_subs = {}
        self.warning_msgs = []
        self.colnames_to_display: Dict[str, List[str]] = {}
        self.cols_to_display = {}
        self.colnos_to_display: Dict[str, List[int]] = {}
        self.display_select_columns = {}
        self.extracted_cols: Dict[str, Any] = {}
        self.extracted_col_names: Dict[str, List[str]] = {}
        self.extracted_col_nos: Dict[str, List[int]] = {}
        self.retrieved_col_names: Dict[str, List[str]] = {}
        self.conn = None
        self.levels_to_write = None
        self.module_conf = None
        self.output_basename = None
        self.extract_columns_multilevel: Dict[str, List[str]] = {}
        self.logger = None
        self.error_logger = None
        self.unique_excs = None
        self.mapper_name: str = ""
        self.no_log = False
        self.colcount = {}
        self.columns: Dict[str, List[Dict[str, Any]]] = {}
        self.conns = []
        self.logtofile = logtofile
        self.dictrow: bool = True
        if self.__module__ == "__main__":
            fp = None
            main_fpath = None
        else:
            fp = sys.modules[self.__module__].__file__
            if not fp:
                raise ModuleLoadingError(module_name=self.__module__)
            main_fpath = Path(fp).resolve()
        if not main_fpath:
            if name:
                self.module_name = name
                self.module_dir = Path(os.getcwd()).resolve()
            else:
                raise ModuleLoadingError(msg="name argument should be given.")
            self.conf = module_conf.copy()
        else:
            self.module_name = main_fpath.stem
            self.module_dir = main_fpath.parent
            self.conf = get_module_conf(
                self.module_name,
                module_type=self.module_type,
                module_dir=self.module_dir,
            )
            if not self.conf:
                self.conf = {}
        self.gene_summary_datas = {}
        self.total_norows: Optional[int] = None
        self.legacy_samples_col = False
        self.df_mode = df_mode
        self.modules_to_add_to_base = []
        self.check_and_setup_args()
        self._setup_logger()

    def exec_db(self, func, *args, **kwargs):
        from ..exceptions import DatabaseConnectionError

        conn = self.get_db_conn()
        if not conn:
            raise DatabaseConnectionError(self.module_name)
        cursor = conn.cursor()
        try:
            ret = func(*args, conn=conn, cursor=cursor, **kwargs)
        except:
            cursor.close()
            raise
        cursor.close()
        return ret

    def check_and_setup_args(self):
        import sqlite3
        import duckdb
        from pathlib import Path
        from ..module.local import get_module_conf
        from ..exceptions import WrongInput

        if not self.df_mode and not Path(self.dbpath).exists():
            raise WrongInput(msg=self.dbpath)
        if not self.df_mode:
            try:
                if self.use_duckdb:
                    with duckdb.connect(self.dbpath) as db:
                        db.execute("select count(*) from info")
                        db.execute("select count(*) from variant")
                else:
                    with sqlite3.connect(self.dbpath) as db:
                        db.execute("select count(*) from info")
                        db.execute("select count(*) from variant")
            except Exception:
                raise WrongInput(msg=f"{self.dbpath} is not an OakVar result database")
        if not self.output_dir:
            self.output_dir = str(Path(self.dbpath).parent)
        if not self.output_dir:
            self.output_dir = Path(".").resolve()
        if self.savepath and self.savepath.parent == "":
            self.savepath = self.output_dir / self.savepath
        self.module_conf = get_module_conf(self.module_name, module_type="reporter")
        self.confs = self.module_options  # TODO: backward compatibility. Delete later.
        self.output_basename = Path(self.dbpath).name[:-7]
        if self.cols:
            self.extract_columns_multilevel = {}
            for level in ["variant", "gene", "sample", "mapping"]:
                self.extract_columns_multilevel[level] = self.cols
        else:
            self.extract_columns_multilevel = self.get_extract_columns_multilevel_from_option(
                self.module_options.get("extract_columns", {})
            )
        self.add_summary = not self.no_summary

    def should_write_level(self, level):
        if self.levels_to_write is None:
            return True
        elif level in self.levels_to_write:
            return True
        else:
            return False

    def connect_db(self, dbpath=None):
        _ = dbpath

    def set_legacy_samples_column_flag(self):
        import sqlite3
        import duckdb

        if not self.dbpath:
            raise
        if self.use_duckdb:
            conn = duckdb.connect(self.dbpath)
        else:
            conn = sqlite3.connect(self.dbpath)
        cursor = conn.cursor()
        q = "pragma table_info(variant)"
        cursor.execute(q)
        header_cols = [row[1] for row in cursor.fetchall()]
        if "tagsampler__samples" in header_cols:
            self.legacy_samples_col = False
        elif "base__samples" in header_cols:
            self.legacy_samples_col = True
        else:
            raise
        cursor.close()
        conn.close()

    def prep(self, user=None):
        from ..system.consts import DEFAULT_SERVER_DEFAULT_USERNAME

        if user is None:
            user = DEFAULT_SERVER_DEFAULT_USERNAME
        self.set_dbpath()
        self.connect_db(dbpath=self.dbpath)
        self.set_legacy_samples_column_flag()
        self.load_filter(user=user)

    def _setup_logger(self):
        import logging
        from ..util.run import set_logger_handler

        if self.module_name is None or self.output_dir is None or self.savepath is None:
            return
        if getattr(self, "no_log", False):
            return
        try:
            self.logger = logging.getLogger(self.module_name)
            self.error_logger = logging.getLogger("err." + self.module_name)
            set_logger_handler(
                self.logger,
                self.error_logger,
                output_dir=Path(self.output_dir),
                run_name=self.run_name,
                mode="a",
                logtofile=self.logtofile,
            )
        except Exception as e:
            self._log_exception(e)
        self.unique_excs = []

    def get_db_conn(self):
        import sqlite3
        import duckdb

        if self.dbpath is None:
            return None
        if not self.conn:
            if self.use_duckdb:
                self.conn = duckdb.connect(self.dbpath)
            else:
                self.conn = sqlite3.connect(self.dbpath)
            self.conns.append(self.conn)
        return self.conn

    def _log_exception(self, e, halt=True):
        if halt:
            raise e
        elif self.logger:
            self.logger.exception(e)

    def substitute_val(self, level, row):
        from json import loads
        from json import dumps

        idx: int = -1
        for sub in self.column_subs.get(level, []):
            col_name = f"{sub.module}__{sub.col}"
            if self.dictrow:
                value = row[col_name]
            else:
                if col_name not in self.retrieved_col_names[level]:
                    continue
                idx = self.retrieved_col_names[level].index(col_name)
                value = row[idx]
            if value is None or value == "" or value == "{}":
                continue
            if (
                level == "variant"
                and sub.module == "base"
                and sub.col == "all_mappings"
            ):
                mappings = loads(value)
                for gene in mappings:
                    for i in range(len(mappings[gene])):
                        sos = mappings[gene][i][2].split(",")
                        sos = [sub.subs.get(so, so) for so in sos]
                        mappings[gene][i][2] = ",".join(sos)
                value = dumps(mappings)
            elif level == "gene" and sub.module == "base" and sub.col == "all_so":
                vals = []
                for i, so_count in enumerate(value.split(",")):
                    so = so_count[:3]
                    so = sub.subs.get(so, so)
                    so_count = so + so_count[3:]
                    vals.append(so_count)
                value = ",".join(vals)
            else:
                value = sub.subs.get(value, value)
            if self.dictrow:
                row[col_name] = value
            else:
                row[idx] = value
        return row

    def get_extracted_header_columns(self, level):
        cols = []
        for col in self.colinfo[level]["columns"]:
            if col["col_name"] in self.colnames_to_display[level]:
                cols.append(col)
        return cols

    def get_db_col_name(self, mi, col):
        if mi.name in ["gencode", "hg38", "tagsampler"]:
            grp_name = "base"
        else:
            grp_name = mi.name
        return f"{grp_name}__{col['name']}"

    def col_is_categorical(self, col):
        return "category" in col and col["category"] in ["single", "multi"]

    def do_gene_level_summary(self, add_summary=True):
        _ = add_summary
        self.gene_summary_datas = {}
        if not self.summarizing_modules:
            return self.gene_summary_datas
        for mi, module_instance, summary_cols in self.summarizing_modules:
            gene_summary_data = module_instance.get_gene_summary_data(self.cf)
            self.gene_summary_datas[mi.name] = [gene_summary_data, summary_cols]
            columns = self.colinfo["gene"]["columns"]
            for col in summary_cols:
                if not self.col_is_categorical(col):
                    continue
                colinfo_col = {}
                colno = None
                for i in range(len(columns)):
                    if columns[i]["col_name"] == self.get_db_col_name(mi, col):
                        colno = i
                        break
                cats = []
                for hugo in gene_summary_data:
                    val = gene_summary_data[hugo][col["name"]]
                    repsub = colinfo_col.get("reportsub", [])
                    if len(repsub) > 0:
                        if val in repsub:
                            val = repsub[val]
                    if val not in cats:
                        cats.append(val)
                if colno is not None:
                    columns[colno]["col_cats"] = cats

    def store_mapper(self, conn=None, cursor=None):
        from ..exceptions import DatabaseConnectionError

        if conn is None or cursor is None:
            raise DatabaseConnectionError(self.module_name)
        q = 'select colval from info where colkey="_mapper"'
        cursor.execute(q)
        r = cursor.fetchone()
        if r is None:
            self.mapper_name = "gencode"
        else:
            self.mapper_name = str(r[0].split(":")[0])

    def write_log(self, msg):
        if not self.logger:
            return
        self.logger.info(msg)

    def log_run_start(self):
        from time import asctime, localtime
        import oyaml as yaml
        from ..util.run import update_status

        self.write_log("started: %s" % asctime(localtime(self.start_time)))
        if self.cf and self.cf.filter:
            self.write_log(f"filter:\n{yaml.dump(self.filter)}")
        if self.module_conf:
            status = f"started {self.module_conf['title']} ({self.module_name})"
            update_status(status, logger=self.logger, serveradmindb=self.serveradmindb)

    def get_levels_to_run(self, tab: str) -> List[str]:
        if not self.cf:
            return []
        if tab == "all":
            levels = self.cf.exec_db(self.cf.get_result_levels)
        else:
            levels = [tab]
        if type(levels) is not list:
            return []
        if not levels:
            return []
        return levels

    def run_df(self, df: pl.DataFrame, columns: List[Dict[str, Any]], savepath: str = ""):
        self.write_data_df(df, columns, savepath)
        self.end()

    def run_3(
        self,
        tab="all",
        add_summary=None,
        pagesize=None,
        page=None,
        make_filtered_table=True,
        user=None,
    ):
        from ..exceptions import SetupError
        from time import time
        from time import asctime
        from time import localtime
        from ..util.run import update_status
        from ..system.consts import DEFAULT_SERVER_DEFAULT_USERNAME

        if user is None:
            user = DEFAULT_SERVER_DEFAULT_USERNAME
        try:
            # TODO: disabling gene level summary for now. Enable later.
            add_summary = False
            if add_summary is None:
                add_summary = self.add_summary
            self.prep()
            if not self.cf:
                raise SetupError(self.module_name)
            self.start_time = time()
            ret = None
            tab = tab or self.level or "all"
            self.log_run_start()
            if self.setup() is False:
                self.close_db()
                raise SetupError(self.module_name)
            self.ftable_uid = self.cf.make_ftables_and_ftable_uid(
                make_filtered_table=make_filtered_table
            )
            self.levels = self.get_levels_to_run(tab)
            for level in self.levels:
                self.level = level
                self.make_col_infos(add_summary=add_summary)
                self.write_data(
                    level,
                    pagesize=pagesize,
                    page=page,
                    make_filtered_table=make_filtered_table,
                    add_summary=add_summary,
                )
            self.close_db()
            if self.module_conf:
                status = f"finished {self.module_conf['title']} ({self.module_name})"
                update_status(
                    status, logger=self.logger, serveradmindb=self.serveradmindb
                )
            end_time = time()
            if not (hasattr(self, "no_log") and self.no_log) and self.logger:
                self.logger.info("finished: {0}".format(asctime(localtime(end_time))))
                run_time = end_time - self.start_time
                self.logger.info("runtime: {0:0.3f}".format(run_time))
            ret = self.end()
            return ret
        except Exception as e:
            self.close_db()
            import traceback

    def run(
        self,
        tab="all",
        add_summary=None,
        pagesize=None,
        page=None,
        make_filtered_table=True,
        user=None,
    ):
        from ..exceptions import SetupError
        from time import time
        from time import asctime
        from time import localtime
        from ..util.run import update_status
        from ..system.consts import DEFAULT_SERVER_DEFAULT_USERNAME

        if user is None:
            user = DEFAULT_SERVER_DEFAULT_USERNAME
        try:
            # TODO: disabling gene level summary for now. Enable later.
            add_summary = False
            if add_summary is None:
                add_summary = self.add_summary
            self.prep()
            if not self.cf:
                raise SetupError(self.module_name)
            self.start_time = time()
            ret = None
            tab = tab or self.level or "all"
            self.log_run_start()
            if self.setup() is False:
                self.close_db()
                raise SetupError(self.module_name)
            self.ftable_uid = self.cf.make_ftables_and_ftable_uid(
                make_filtered_table=make_filtered_table
            )
            self.levels = self.get_levels_to_run(tab)
            for level in self.levels:
                self.level = level
                self.make_col_infos(add_summary=add_summary)
                self.write_data(
                    level,
                    pagesize=pagesize,
                    page=page,
                    make_filtered_table=make_filtered_table,
                    add_summary=add_summary,
                )
            self.close_db()
            if self.module_conf:
                status = f"finished {self.module_conf['title']} ({self.module_name})"
                update_status(
                    status, logger=self.logger, serveradmindb=self.serveradmindb
                )
            end_time = time()
            if not (hasattr(self, "no_log") and self.no_log) and self.logger:
                self.logger.info("finished: {0}".format(asctime(localtime(end_time))))
                run_time = end_time - self.start_time
                self.logger.info("runtime: {0:0.3f}".format(run_time))
            ret = self.end()
            return ret
        except Exception as e:
            self.close_db()
            import traceback

            traceback.print_exc()
            raise e

    def write_preface_df(self, df, columns):
        pass

    def write_header_df(self, columns):
        pass

    def write_data_df(
        self, df, columns, savepath
    ):
        import time
        import copy
        from ..exceptions import SetupError

        colnos = {columns[i]["name"]: i for i in range(len(columns))}
        self.write_preface_df(df, savepath)
        self.write_header_df(columns)
        #self.extracted_cols[level] = self.get_extracted_header_columns(level)
        #self.extracted_col_names[level] = [
        #    col_def.get("col_name") for col_def in self.extracted_cols[level]
        #]
        #self.hugo_colno = self.colnos[level].get("base__hugo", None)
        #datacols = self.cf.exec_db(self.cf.get_variant_data_cols)
        #self.total_norows = self.cf.exec_db(
        #    self.cf.get_ftable_num_rows, level=level, uid=self.ftable_uid, ftype=level
        #)  # type: ignore
        #if datacols is None or self.total_norows is None:
        #    return
        #if level == "variant" and self.separatesample:
        #    self.write_variant_sample_separately = True
        #else:
        #    self.write_variant_sample_separately = False
        row_count = 0
        #conn_read, conn_write = self.cf.get_db_conns()
        #if not conn_read or not conn_write:
        #    return None
        #cursor_read = conn_read.cursor()
        #self.cf.get_level_data_iterator(
        #    level, page=page, pagesize=pagesize, uid=self.ftable_uid, cursor_read=cursor_read, var_added_cols=self.var_added_cols
        #)
        ctime = time.time()
        #self.retrieved_col_names[level] = [d[0] for d in cursor_read.description]
        #self.extracted_col_nos[level] = [self.retrieved_col_names[level].index(col_name) for col_name in self.extracted_col_names[level]]
        #self.num_retrieved_cols = len(self.retrieved_col_names[level])
        #self.colnos_to_display[level] = [self.retrieved_col_names[level].index(c) for c in self.colnames_to_display[level]]
        #self.extracted_colnos_in_retrieved = [self.retrieved_col_names[level].index(c) for c in self.extracted_col_names[level]]
        self.vcf_format = False
        self.level = "variant"
        self.extracted_col_names = {"variant": copy.deepcopy(df.columns)}
        for datarow in df.iter_rows():
            #self.stringify_all_mapping(level, datarow)
            self.escape_characters_df(datarow)
            self.write_row_with_samples_separate_or_not_df(datarow, columns, colnos)
            row_count += 1
            if row_count % 10000 == 0:
                t = time.time()
                msg = f"Wrote {row_count} rows. {(t - ctime) / row_count}"
                if self.logger is not None:
                    self.logger.info(msg)
                elif self.outer is not None:
                    self.outer.write(msg)

    def write_data(
        self,
        level: str,
        add_summary=True,
        pagesize=None,
        page=None,
        make_filtered_table=True,
    ):
        import time
        from ..exceptions import SetupError

        _ = make_filtered_table
        if self.should_write_level(level) is False:
            return
        if not self.exec_db(self.table_exists, level):
            return
        if not self.cf:
            raise SetupError(self.module_name)
        if add_summary and self.level == "gene":
            self.do_gene_level_summary(add_summary=add_summary)
        self.write_preface(level)
        self.extracted_cols[level] = self.get_extracted_header_columns(level)
        self.extracted_col_names[level] = [
            col_def.get("col_name") for col_def in self.extracted_cols[level]
        ]
        self.write_header(level)
        self.hugo_colno = self.colnos[level].get("base__hugo", None)
        datacols = self.cf.exec_db(self.cf.get_variant_data_cols)
        self.total_norows = self.cf.exec_db(
            self.cf.get_ftable_num_rows, level=level, uid=self.ftable_uid, ftype=level
        )  # type: ignore
        if datacols is None or self.total_norows is None:
            return
        if level == "variant" and self.separatesample:
            self.write_variant_sample_separately = True
        else:
            self.write_variant_sample_separately = False
        row_count = 0
        conn_read, conn_write = self.cf.get_db_conns()
        if not conn_read or not conn_write:
            return None
        cursor_read = conn_read.cursor()
        self.cf.get_level_data_iterator(
            level, page=page, pagesize=pagesize, uid=self.ftable_uid, cursor_read=cursor_read, var_added_cols=self.var_added_cols
        )
        ctime = time.time()
        self.retrieved_col_names[level] = [d[0] for d in cursor_read.description]
        self.extracted_col_nos[level] = [self.retrieved_col_names[level].index(col_name) for col_name in self.extracted_col_names[level]]
        self.num_retrieved_cols = len(self.retrieved_col_names[level])
        self.colnos_to_display[level] = [self.retrieved_col_names[level].index(c) for c in self.colnames_to_display[level]]
        self.extracted_colnos_in_retrieved = [self.retrieved_col_names[level].index(c) for c in self.extracted_col_names[level]]
        for datarow in cursor_read:
            if self.dictrow:
                datarow = dict(datarow)
            else:
                datarow = list(datarow)
            if level == "gene" and add_summary:
                self.add_gene_summary_data_to_gene_level(datarow)
            datarow = self.substitute_val(level, datarow)
            self.stringify_all_mapping(level, datarow)
            self.escape_characters(datarow)
            self.write_row_with_samples_separate_or_not(datarow)
            row_count += 1
            if row_count % 10000 == 0:
                t = time.time()
                msg = f"Wrote {row_count} rows. {(t - ctime) / row_count}"
                if self.logger is not None:
                    self.logger.info(msg)
                elif self.outer is not None:
                    self.outer.write(msg)
            if pagesize and row_count == pagesize:
                break
        cursor_read.close()
        conn_read.close()
        conn_write.close()

    def write_table_row_df(self, datarow, columns):
        pass

    def write_row_with_samples_separate_or_not_df(self, datarow, columns, colnos):
        self.write_table_row_df(datarow, columns)

    def write_row_with_samples_separate_or_not(self, datarow):
        if self.legacy_samples_col:
            col_name = "base__samples"
        else:
            col_name = "tagsampler__samples"
        if self.write_variant_sample_separately:
            samples = datarow[col_name]
            if samples:
                samples = samples.split(";")
                for sample in samples:
                    sample_datarow = datarow
                    sample_datarow[col_name] = sample
                    self.write_table_row(self.get_extracted_row(sample_datarow))
            else:
                self.write_table_row(self.get_extracted_row(datarow))
        else:
            self.write_table_row(self.get_extracted_row(datarow))

    def escape_characters_df(self, datarow):
        for i, v in enumerate(datarow):
            if isinstance(v, str) and "\n" in v:
                datarow[i] = v.replace("\n", "%0A")

    def escape_characters(self, datarow):
        if self.dictrow:
            for k, v in datarow.items():
                if isinstance(v, str) and "\n" in v:
                    datarow[k] = v.replace("\n", "%0A")
        else:
            for col_no in range(self.num_retrieved_cols):
                v = datarow[col_no]
                if isinstance(v, str) and "\n" in v:
                    datarow[col_no] = v.replace("\n", "%0A")

    def stringify_all_mapping(self, level, datarow):
        from json import loads

        if hasattr(self, "keep_json_all_mapping") is True or level != "variant":
            return
        col_name = "base__all_mappings"
        idx: Optional[int] = None
        if self.dictrow:
            all_map = loads(datarow[col_name])
        else:
            if col_name not in self.retrieved_col_names[level]:
                return
            idx = self.retrieved_col_names[level].index(col_name)
            all_map = loads(datarow[idx])
        newvals = []
        for hugo in all_map:
            for maprow in all_map[hugo]:
                if len(maprow) == 5:
                    # TODO: remove this after a while. Now is 10/22/2022.
                    [protid, protchange, so, transcript, rnachange] = maprow
                    exonno = ""
                else:
                    [protid, protchange, so, transcript, rnachange, exonno] = maprow
                if protid is None:
                    protid = "(na)"
                if protchange is None:
                    protchange = "(na)"
                if rnachange is None:
                    rnachange = "(na)"
                newval = (
                    f"{transcript}:{hugo}:{protid}:{so}:{protchange}"
                    + f":{rnachange}:{exonno}"
                )
                newvals.append(newval)
        newvals.sort()
        newcell = "; ".join(newvals)
        if self.dictrow:
            datarow[col_name] = newcell
        elif idx is not None:
            datarow[idx] = newcell

    def add_gene_summary_data_to_gene_level(self, datarow):
        hugo = datarow["base__hugo"]
        for mi, _, _ in self.summarizing_modules:
            module_name = mi.name
            [gene_summary_data, cols] = self.gene_summary_datas[module_name]
            grp_name = "base" if self.should_be_in_base(module_name) else module_name
            if (
                hugo in gene_summary_data
                and gene_summary_data[hugo] is not None
                and len(gene_summary_data[hugo]) == len(cols)
            ):
                datarow.update(
                    {
                        f"{grp_name}__{col['name']}": gene_summary_data[hugo][
                            col["name"]
                        ]
                        for col in cols
                    }
                )
            else:
                datarow.update({f"{grp_name}__{col['name']}": None for col in cols})

    def add_gene_level_data_to_variant_level(self, datarow):
        if self.nogenelevelonvariantlevel or self.hugo_colno is None or not self.cf:
            return
        generow = self.cf.exec_db(self.cf.get_gene_row, datarow["base__hugo"])
        if generow is None:
            datarow.update({col: None for col in self.var_added_cols})
        else:
            datarow.update({col: generow[col] for col in self.var_added_cols})

    def get_variant_colinfo(self, add_summary=True):
        try:
            self.prep()
            if self.setup() is False:
                self.close_db()
                return None
            self.levels = self.get_levels_to_run("all")
            self.make_col_infos(add_summary=add_summary)
            return self.colinfo
        except Exception:
            import traceback

            traceback.print_exc()
            self.close_db()
            return None

    def setup(self):
        pass

    def end(self):
        self.flush()

    def flush(self):
        pass

    def write_preface(self, __level__: str):
        pass

    def write_header(self, __level__: str):
        pass

    def write_table_row(self, __row__: Union[Dict[str, Any], List[Any]]):
        pass

    def get_extracted_row(self, row) -> Union[Dict[str, Any], List[Any]]:
        if not self.level:
            return row
        if self.dictrow:
            filtered_row = {col: row[col] for col in self.cols_to_display[self.level]}
        else:
            filtered_row = [row[colno] for colno in self.colnos_to_display[self.level]]
        return filtered_row

    def add_to_colnames_to_display(self, level, column):
        """
        include columns according to --cols option
        """
        col_name = column["col_name"]
        if (
            level in self.extract_columns_multilevel
            and len(self.extract_columns_multilevel[level]) > 0
        ):
            if col_name in self.extract_columns_multilevel[level]:
                incl = True
            else:
                incl = False
        else:
            incl = True
        if incl and col_name not in self.colnames_to_display[level]:
            self.colnames_to_display[level].append(col_name)

    def make_sorted_column_groups(self, level, conn=Any):
        cursor = conn.cursor()
        self.columngroups[level] = []
        sql = f"select name, displayname from {level}_annotator order by name"
        cursor.execute(sql)
        rows = cursor.fetchall()
        for row in rows:
            (name, displayname) = row
            if name == "base":
                self.columngroups[level].append(
                    {"name": name, "displayname": displayname, "count": 0}
                )
                break
        for row in rows:
            (name, displayname) = row
            if name in self.modules_to_add_to_base:
                self.columngroups[level].append(
                    {"name": name, "displayname": displayname, "count": 0}
                )
        for row in rows:
            (name, displayname) = row
            if name != "base" and name not in self.modules_to_add_to_base:
                self.columngroups[level].append(
                    {"name": name, "displayname": displayname, "count": 0}
                )

    def make_coldefs(self, level, conn=Any, group_name=None) -> List[ColumnDefinition]:
        coldefs: List[ColumnDefinition] = []
        if not conn:
            return coldefs
        cursor = conn.cursor()
        header_table = f"{level}_header"
        group_names = []
        if group_name:
            group_names.append(group_name)
            sql = (
                f"select col_name, col_def from {header_table} where "
                + f"col_name like '{group_name}__%'"
            )
        else:
            group_names = [d.get("name") for d in self.columngroups[level]]
        for group_name in group_names:
            sql = (
                f"select col_def from {header_table} where col_name "
                + f"like '{group_name}__%'"
            )
            cursor.execute(sql)
            rows = cursor.fetchall()
            for row in rows:
                coljson = row[0]
                # group_name = col_name.split("__")[0]
                if group_name == "base" or group_name in self.modules_to_add_to_base:
                    coldef = ColumnDefinition({})
                    coldef.from_json(coljson)
                    coldef.level = level
                    coldef = self.gather_col_categories(level, coldef, conn)
                    coldefs.append(coldef)
            for row in rows:
                coljson = row[0]
                # group_name = col_name.split("__")[0]
                if group_name == "base" or group_name in self.modules_to_add_to_base:
                    continue
                coldef = ColumnDefinition({})
                coldef.from_json(coljson)
                coldef.level = level
                coldef = self.gather_col_categories(level, coldef, conn)
                coldefs.append(coldef)
        return coldefs

    def gather_col_categories(self, level, coldef, conn):
        cursor = conn.cursor()
        if coldef.category not in ["single", "multi"] or len(coldef.categories) > 0:
            return coldef
        sql = f"select distinct {coldef.name} from {level}"
        cursor.execute(sql)
        rs = cursor.fetchall()
        for r in rs:
            coldef.categories.append(r[0])
        return coldef

    def make_columns_colnos_colnamestodisplay_columngroup(self, level, coldefs: List[ColumnDefinition]):
        self.columns[level] = []
        self.colnos[level] = {}
        self.colcount[level] = 0
        for coldef in coldefs:
            self.colnos[level][coldef.name] = self.colcount[level]
            self.colcount[level] += 1
            [colgrpname, _] = self.get_group_field_names(coldef.name)
            column = coldef.get_colinfo()
            self.columns[level].append(column)
            self.add_to_colnames_to_display(level, column)
            for columngroup in self.columngroups[level]:
                if columngroup["name"] == colgrpname:
                    columngroup["count"] += 1

    def get_gene_level_modules_to_add_to_variant_level(self, conn):
        cursor = conn.cursor()
        q = "select name from gene_annotator"
        cursor.execute(q)
        gene_annotators = [v[0] for v in cursor.fetchall()]
        modules_to_add = [m for m in gene_annotators if m != "base"]
        return modules_to_add

    def add_gene_level_displayname_to_variant_level_columngroups(
        self, module_name, coldefs, conn
    ):
        cursor = conn.cursor()
        q = "select displayname from gene_annotator where name=?"
        cursor.execute(q, (module_name,))
        r = cursor.fetchone()
        displayname = r[0]
        self.columngroups["variant"].append(
            {"name": module_name, "displayname": displayname, "count": len(coldefs)}
        )

    def add_gene_level_columns_to_variant_level(self, conn):
        if not self.exec_db(self.table_exists, "gene"):
            return
        modules_to_add = self.get_gene_level_modules_to_add_to_variant_level(conn)
        for module_name in modules_to_add:
            gene_coldefs = self.make_coldefs(
                "gene", conn=conn, group_name=module_name
            )
            if not gene_coldefs:
                continue
            self.add_gene_level_displayname_to_variant_level_columngroups(
                module_name, gene_coldefs, conn
            )
            for gene_coldef in gene_coldefs:
                self.colnos["variant"][gene_coldef.name] = self.colcount["variant"]
                self.colcount["variant"] += 1
                gene_column = gene_coldef.get_colinfo()
                self.columns["variant"].append(gene_column)
                self.add_to_colnames_to_display("variant", gene_column)
                self.var_added_cols.append(gene_coldef.name)

    def add_gene_level_summary_columns(
        self, add_summary=True, conn=Any, cursor=Any
    ):
        from os.path import dirname
        import sys
        from ..exceptions import ModuleLoadingError
        from ..module.local import get_local_module_infos_of_type
        from ..module.local import get_local_module_info
        from ..util.inout import ColumnDefinition
        from ..util.module import get_annotator
        from ..util.module import get_mapper

        _ = conn
        if not add_summary:
            return
        q = "select name from variant_annotator"
        cursor.execute(q)
        done_var_annotators = [v[0] for v in cursor.fetchall()]
        self.summarizing_modules = []
        local_modules = get_local_module_infos_of_type("annotator")
        local_modules.update(get_local_module_infos_of_type("postaggregator"))
        summarizer_module_names = []
        for module_name in done_var_annotators:
            if module_name == self.mapper_name or module_name in [
                "base",
                "hg38",
                "hg19",
                "hg18",
                "extra_vcf_info",
                "extra_variant_info",
                "original_input",
            ]:
                continue
            if module_name not in local_modules:
                if self.logger:
                    self.logger.info(
                        f"Skipping gene level summarization with {module_name} "
                        + "as it does not exist in the system."
                    )
                continue
            module = local_modules[module_name]
            if "can_summarize_by_gene" in module.conf:
                summarizer_module_names.append(module_name)
        mapper = get_local_module_info(self.mapper_name)
        if not mapper:
            raise ModuleLoadingError(module_name=self.mapper_name)
        local_modules[self.mapper_name] = mapper
        summarizer_module_names = [self.mapper_name] + summarizer_module_names
        for module_name in summarizer_module_names:
            if not module_name:
                continue
            mi = local_modules[module_name]
            if not mi:
                continue
            cmd = {
                "output_dir": self.output_dir,
                "serveradmindb": self.serveradmindb,
            }
            sys.path = sys.path + [dirname(mi.script_path)]
            if mi.name in done_var_annotators:
                annot = get_annotator(module_name, **cmd)
            elif mi.name == self.mapper_name:
                annot = get_mapper(module_name, **cmd)
            else:
                continue
            cols = mi.conf["gene_summary_output_columns"]
            columngroup = {
                "name": mi.name,
                "displayname": mi.title,
                "count": len(cols),
            }
            level = "gene"
            self.columngroups[level].append(columngroup)
            for col in cols:
                coldef = ColumnDefinition(col)
                if self.should_be_in_base(mi.name):
                    coldef.name = f"base__{coldef.name}"
                else:
                    coldef.name = f"{mi.name}__{coldef.name}"
                coldef.genesummary = True
                column = coldef.get_colinfo()
                self.columns[level].append(column)
                self.add_to_colnames_to_display(level, column)
                self.colnos[level][coldef.name] = len(self.colnos[level])
            self.summarizing_modules.append([mi, annot, cols])

    def should_be_in_base(self, name):
        if "__" in name:
            name = self.get_group_name(name)
        return name in self.modules_to_add_to_base

    def get_group_field_names(self, col_name):
        return col_name.split("__")

    def get_group_name(self, col_name):
        return self.get_group_field_names(col_name)[0]

    def make_report_sub(self, level, conn):
        from json import loads
        from types import SimpleNamespace

        if level not in ["variant", "gene"]:
            return
        reportsubtable = f"{level}_reportsub"
        if not self.exec_db(self.table_exists, reportsubtable):
            return
        cursor = conn.cursor()
        q = f"select * from {reportsubtable}"
        cursor.execute(q)
        reportsub = {r[0]: loads(r[1]) for r in cursor.fetchall()}
        self.column_subs[level] = []
        for i, column in enumerate(self.columns[level]):
            module_name, field_name = self.get_group_field_names(column["col_name"])
            if module_name == self.mapper_name:
                module_name = "base"
            if module_name in reportsub and field_name in reportsub[module_name]:
                self.column_subs[level].append(
                    SimpleNamespace(
                        module=module_name,
                        col=field_name,
                        index=i,
                        subs=reportsub[module_name][field_name],
                    )
                )
                self.columns[level][i]["reportsub"] = reportsub[module_name][field_name]

    def set_display_select_columns(self, level):
        if self.extract_columns_multilevel.get(level, {}):
            self.display_select_columns[level] = True
        else:
            self.display_select_columns[level] = False

    def set_cols_to_display(self, level):
        self.cols_to_display[level] = []
        self.colnos_to_display[level] = []
        colno = 0
        for col in self.columns[level]:
            col_name = col["col_name"]
            if col_name in self.colnames_to_display[level]:
                self.cols_to_display[level].append(col_name)
                self.colnos_to_display[level].append(colno)
            colno += 1

    def make_col_infos(self, add_summary=True):
        prev_level = self.level
        for level in self.levels:
            self.level = level
            self.exec_db(self.make_col_info, level, add_summary=add_summary)
        self.level = prev_level

    def add_column_number_stat_to_col_groups(self, level: str):
        last_columngroup_pos = 0
        for columngroup in self.columngroups.get(level, []):
            columngroup["start_column_number"] = last_columngroup_pos
            new_last_columngroup_pos = last_columngroup_pos + columngroup["count"]
            columngroup["end_colunm_number"] = new_last_columngroup_pos
            last_columngroup_pos = new_last_columngroup_pos

    def make_col_info(self, level: str, add_summary=True, conn=Any, cursor=Any):
        _ = cursor
        if not level or not self.exec_db(self.table_exists, level):
            return
        self.exec_db(self.store_mapper)
        self.colnames_to_display[level] = []
        self.modules_to_add_to_base = [self.mapper_name, "tagsampler"]
        self.make_sorted_column_groups(level, conn=conn)
        coldefs = self.make_coldefs(level, conn=conn)
        if not coldefs:
            return
        self.make_columns_colnos_colnamestodisplay_columngroup(level, coldefs)
        if not self.nogenelevelonvariantlevel and self.level == "variant":
            self.add_gene_level_columns_to_variant_level(conn)
        if self.level == "gene" and level == "gene" and add_summary:
            self.exec_db(self.add_gene_level_summary_columns, level)
        self.set_display_select_columns(level)
        self.set_cols_to_display(level)
        self.add_column_number_stat_to_col_groups(level)
        self.colinfo[level] = {
            "colgroups": self.columngroups[level],
            "columns": self.columns[level],
        }
        self.make_report_sub(level, conn)

    def get_extract_columns_multilevel_from_option(self, v: Optional[str]) -> Dict[str, List[str]]:
        import json

        ret: Dict[str, List[str]] = {}
        if isinstance(v, str):
            if v.startswith("{"): # dict
                v = v.replace("'", "\"")
                ret = json.loads(v)
        return ret

    def set_dbpath(self, dbpath: str=""):
        from os.path import exists
        from ..exceptions import NoInput
        from ..exceptions import WrongInput

        if dbpath:
            self.dbpath = dbpath
        if not self.dbpath:
            raise NoInput()
        if not exists(self.dbpath):
            raise WrongInput()

    def close_db(self):
        for conn in self.conns:
            conn.close()
        self.conns = []
        if self.cf is not None:
            self.cf.close_db()
            self.cf = None

    def load_filter(self, user=None):
        from ... import ReportFilter
        from ..system.consts import DEFAULT_SERVER_DEFAULT_USERNAME

        if user is None:
            user = DEFAULT_SERVER_DEFAULT_USERNAME
        self.cf = ReportFilter.create(dbpath=self.dbpath, user=user, strict=False)
        self.cf.exec_db(
            self.cf.loadfilter,
            filter=self.filter,
            filterpath=self.filterpath,
            filtername=self.filtername,
            filterstring=self.filterstring,
            filtersql=self.filtersql,
            includesample=self.includesample,
            excludesample=self.excludesample,
        )

    def table_exists(self, tablename, conn=None, cursor=None):
        if conn is None:
            pass
        if cursor is None:
            from ..exceptions import SetupError

            raise SetupError()
        sql = (
            "select name from sqlite_master where "
            + 'type="table" and name="'
            + tablename
            + '"'
        )
        cursor.execute(sql)
        row = cursor.fetchone()
        if row is None:
            ret = False
        else:
            ret = True
        return ret

    def get_standardized_module_option(self, v: Any) -> Any:
        from ..util.run import get_standardized_module_option

        return get_standardized_module_option(v)

CravatReport = BaseReporter
