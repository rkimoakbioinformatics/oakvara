from typing import Optional
from typing import List
from pathlib import Path


def pack(
    module_name: Optional[str] = None,
    outdir: Path = Path(".").absolute(),
    code_only: bool = False,
    split: bool = False,
    outer=None,
):
    from ...lib.module.local import pack_module

    if not module_name:
        return
    if isinstance(outdir, str):
        outdir = Path(outdir).absolute()
    ret = pack_module(
        module_name=module_name,
        outdir=outdir,
        code_only=code_only,
        split=split,
        outer=outer,
    )
    return ret


def ls(
    module_names: List[str] = [".*"],
    available: bool = False,
    types: List[str] = [],
    tags: List[str] = [],
    nameonly: bool = False,
    raw_bytes: bool = False,
    outer=None,
    **kwargs,
):
    from .ls_logic import list_modules
    from ...lib.util.util import print_list_of_dict

    _ = kwargs
    ret = list_modules(
        module_names=module_names,
        types=types,
        tags=tags,
        available=available,
        nameonly=nameonly,
        raw_bytes=raw_bytes,
    )
    if outer:
        print_list_of_dict(ret, outer=outer)
    return ret


def info(module_name: Optional[str] = None, local: bool = False, outer=None, **kwargs):
    from ...lib.module.local import get_local_module_info
    from ...lib.module.remote import get_remote_module_info
    from ...lib.module.local import LocalModule
    from ...lib.module.remote import get_readme as get_remote_readme
    from ...lib.module.local import get_readme as get_local_readme
    from ...lib.module.local import get_remote_manifest_from_local
    from ...cli.module.info_fn import print_module_info

    _ = kwargs
    ret = {}
    if not module_name:
        return None
    installed = False
    remote_available = False
    up_to_date = False
    local_info = None
    remote_info = None
    # Readm
    readme = get_remote_readme(module_name)
    if not readme:
        readme = get_local_readme(module_name)
    ret["readme"] = readme
    # Remote
    remote_info = get_remote_module_info(module_name)
    remote_available = remote_info != None
    # Local
    local_info = get_local_module_info(module_name)
    if local_info:
        installed = True
    else:
        installed = False
    if remote_available and remote_info:
        ret["store_availability"] = True
    else:
        ret["store_availability"] = False
    if not remote_available and not installed:
        return None
    if remote_available and remote_info:
        ret.update(remote_info.to_info())
        ret["output_columns"] = []
        if remote_info.output_columns:
            for col in remote_info.output_columns:
                desc = ""
                if "desc" in col:
                    desc = col["desc"]
                ret["output_columns"].append(
                    {"name": col["name"], "title": col["title"], "desc": desc}
                )
    elif local_info:
        remote_manifest_from_local = get_remote_manifest_from_local(module_name)
        if remote_manifest_from_local:
            ret.update(remote_manifest_from_local)
            ret["versions"] = {
                remote_manifest_from_local.get("code_version"): {
                    "data_version": remote_manifest_from_local.get("data_version"),
                    "data_source": remote_manifest_from_local.get("data_source"),
                    "min_pkg_ver": remote_manifest_from_local.get("min_pkg_ver"),
                }
            }
            del ret["conf"]
    ret["installed"] = installed
    if installed:
        if local and isinstance(local_info, LocalModule):
            ret["installed_version"] = local_info.code_version
            ret["location"] = local_info.directory
    else:
        pass
    if (
        installed
        and remote_available
        and local_info
        and local_info.code_version
        and remote_info
    ):
        if installed and local_info.code_version >= remote_info.latest_code_version:
            up_to_date = True
        else:
            up_to_date = False
        ret["latest_installed"] = up_to_date
        ret["latest_store_version"] = ret["latest_version"]
        del ret["latest_version"]
        ret["latest_version"] = max(
            local_info.code_version, remote_info.latest_code_version
        )
    if outer:
        print_module_info(module_info=ret, outer=outer)
    return ret


def install(
    module_names: List[str] = [],
    urls: Optional[str] = None,
    modules_dir: Optional[Path] = None,
    overwrite: bool = False,
    clean: bool = False,
    force_data: bool = False,
    yes: bool = False,
    skip_dependencies: bool = False,
    skip_data: bool = False,
    no_fetch: bool = False,
    outer=None,
    stage_handler=None,
    system_worker_state=None,
):
    import sys
    from .install_defs import get_modules_to_install
    from .install_defs import show_modules_to_install
    from ...lib.module import install_module
    from ...lib.module import install_module_from_url
    from ...lib.module import install_module_from_zip_path
    from ...lib.util.run import get_y_or_n
    from ...lib.util.download import is_zip_path
    from ...lib.store.db import try_fetch_ov_store_cache
    from ...lib.exceptions import ModuleToSkipInstallation

    if not no_fetch:
        try_fetch_ov_store_cache(outer=outer)
    to_install = get_modules_to_install(
        module_names=module_names,
        urls=urls,
        skip_dependencies=skip_dependencies,
        outer=outer,
    )
    if len(to_install) == 0:
        if outer:
            outer.write("No module to install")
        return
    show_modules_to_install(to_install, outer=outer)
    if not yes:
        if not get_y_or_n():
            return
    problem_modules = []
    for module_name, data in sorted(to_install.items()):
        module_version = data.get("version")
        install_type = data.get("type")
        url = data.get("url")
        try:
            if install_type == "url":
                if not install_module_from_url(
                    module_name,
                    url,
                    modules_dir=modules_dir,
                    clean=clean,
                    overwrite=overwrite,
                    force_data=force_data,
                    skip_data=skip_data,
                    outer=outer,
                ):
                    problem_modules.append(module_name)
            elif is_zip_path(module_name):
                if not install_module_from_zip_path(
                    module_name, force_data=force_data, skip_data=skip_data, outer=outer
                ):
                    problem_modules.append(module_name)
            else:
                ret = install_module(
                    module_name,
                    version=module_version,
                    force_data=force_data,
                    overwrite=overwrite,
                    stage_handler=stage_handler,
                    skip_data=skip_data,
                    modules_dir=modules_dir,
                    outer=outer,
                    system_worker_state=system_worker_state,
                )
                if not ret:
                    problem_modules.append(module_name)
        except Exception as e:
            if not isinstance(e, ModuleToSkipInstallation):
                if module_name not in problem_modules:
                    problem_modules.append(module_name)
            if outer:
                outer.error(e)
            else:
                sys.stderr.write(str(e) + "\n")
    if problem_modules:
        if outer:
            outer.write(f"Following modules were not installed due to problems:")
        for mn in problem_modules:
            if outer:
                outer.write(f"- {mn}")
        return False
    else:
        return


def update(
    module_name_patterns: List[str] = [],
    refresh_db: bool = False,
    clean_cache_files: bool = False,
    clean: bool = False,
    publish_time: str = "",
    no_fetch: bool = False,
    overwrite: bool = False,
    force_data: bool = False,
    modules_dir: Optional[Path] = None,
    yes=False,
    outer=None,
    system_worker_state=None,
):
    from ...lib.module.local import search_local
    from ...lib.module import get_updatable
    from ...lib.store.db import try_fetch_ov_store_cache

    if not no_fetch:
        try_fetch_ov_store_cache(
            refresh_db=refresh_db,
            clean_cache_files=clean_cache_files,
            clean=clean,
            publish_time=publish_time,
            outer=outer,
        )
    requested_modules = search_local(*module_name_patterns)
    to_update = get_updatable(module_names=requested_modules)
    if not to_update:
        if outer:
            outer.write("No module to update")
        return True
    if not yes:
        if outer:
            outer.write(f"Following modules will be updated.")
            for mn in to_update:
                outer.write(f"- {mn}")
            yn = input("Proceed? (y/N) > ")
            if not yn or yn.lower() not in ["y", "yes"]:
                return True
    ret = install(
        module_names=to_update,
        modules_dir=modules_dir,
        overwrite=overwrite,
        clean=clean,
        force_data=force_data,
        yes=True,
        skip_dependencies=False,
        skip_data=False,
        no_fetch=no_fetch,
        outer=outer,
        system_worker_state=system_worker_state,
    )
    if ret is not None:
        return False
    else:
        return True


def uninstall(module_names: Optional[List[str]] = None, yes: bool = False, outer=None):
    from ...lib.module.local import search_local
    from ...lib.module import uninstall_module
    from ...lib.exceptions import ArgumentError

    if not module_names:
        e = ArgumentError("No modules to uninstall.")
        e.traceback = False
        raise e
    module_names = search_local(*module_names)
    if len(module_names) == 0:
        if outer:
            outer.write("No module to uninstall")
        return True
    if outer:
        outer.write("Uninstalling:")
        for mn in module_names:
            outer.write(f"- {mn}")
    if not yes:
        yn = input("Proceed? (y/N) > ")
        if not yn or yn.lower() != "y":
            return True
    for module_name in module_names:
        uninstall_module(module_name)
    return True


def installbase(
    refresh_db: bool = False,
    clean_cache_files: bool = False,
    clean: bool = False,
    publish_time: str = "",
    no_fetch: bool = False,
    conf: Optional[dict] = None,
    overwrite: bool = False,
    modules_dir: Optional[Path] = None,
    outer=None,
    system_worker_state=None,
):
    from ...lib.system import get_system_conf
    from ...lib.system.consts import base_modules_key
    from ...lib.store.db import try_fetch_ov_store_cache

    if not no_fetch:
        try_fetch_ov_store_cache(
            refresh_db=refresh_db,
            clean_cache_files=clean_cache_files,
            clean=clean,
            publish_time=publish_time,
            outer=outer,
        )
    sys_conf = get_system_conf(conf=conf)
    base_modules: List[str] = sys_conf.get(base_modules_key, [])
    ret = install(
        module_names=base_modules,
        modules_dir=modules_dir,
        overwrite=overwrite,
        clean=clean,
        force_data=False,
        yes=True,
        skip_dependencies=False,
        skip_data=False,
        no_fetch=no_fetch,
        outer=outer,
        system_worker_state=system_worker_state,
    )
    return ret
