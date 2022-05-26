class ConfigLoader:

    def __init__(self, job_conf_path=None):
        from .sysadmin import get_main_conf_path
        from .exceptions import SystemMissingException

        self.job_conf_path = job_conf_path
        self.main_conf_path = get_main_conf_path()
        self._system = {}
        self._main = {}
        self._job = {}
        self._modules = {}
        self._all = {}
        self._load_system_conf(build_all=False)
        self._load_main_conf(build_all=False)
        self._load_job_conf(build_all=False)
        self._build_all()

    def _load_system_conf(self, build_all=True):
        from .sysadmin import get_system_conf

        self._system = get_system_conf()
        if build_all:
            self._build_all()

    def _load_main_conf(self, build_all=True):
        import os
        import copy
        from .admin_util import load_yml_conf, get_packagedir
        import shutil
        from .sysadmin_const import default_multicore_mapper_mode

        self._main = {}
        if os.path.exists(self.main_conf_path) == False:
            shutil.copy(os.path.join(get_packagedir(), "cravat.yml"),
                        self.main_conf_path)
        self._main = load_yml_conf(self.main_conf_path)
        conf_modified = False
        k = "multicore_mapper_mode"
        if k not in self._main:
            self._main[k] = default_multicore_mapper_mode
        if build_all:
            self._build_all()

    def _load_job_conf(self, build_all=True):
        import os
        from .admin_util import load_yml_conf

        self._job = {}
        if self.job_conf_path:
            if os.path.exists(self.job_conf_path):
                self._job = load_yml_conf(self.job_conf_path)
            else:
                print("Job conf file", self.job_conf_path, "does not exist.")
                exit()
        if build_all:
            self._build_all()

    def _load_module_conf(self, module_name, build_all=True):
        from .admin_util import get_module_conf_path, load_yml_conf

        conf_path = get_module_conf_path(module_name)
        if conf_path is not None:
            self._modules[module_name] = load_yml_conf(conf_path)
        if build_all:
            self._build_all()

    def _build_all(self):
        import copy
        from .admin_util import recursive_update

        self._all = {}
        if self._modules:
            self._all["modules"] = copy.deepcopy(self._modules)
        if self._main:
            self._all["cravat"] = copy.deepcopy(self._main)
        if self._system:
            self._all["system"] = copy.deepcopy(self._system)
        self._all = recursive_update(self._all, self._job)
        if "run" not in self._all:
            self._all["run"] = {}
        for k, v in self._all["system"].items():
            if k not in self._all:
                self._all[k] = v
        for k, v in self._all["cravat"].items():
            if k not in self._all:
                self._all[k] = v
        for k, v in self._all["run"].items():
            if k not in self._all:
                self._all[k] = v

    def save(self, path, modules=[]):
        """
        Save all the config settings to a file.
        A list of modules to include may be passed in. An empty list results
        in all module configs being saved.
        """
        import oyaml as yaml
        from .admin_util import list_local

        # Load all modules, or only requested modules
        if len(modules) == 0:
            modules = list_local()
        for module_name in modules:
            self._load_module_conf(module_name, build_all=False)
        self._build_all()
        # Delete configs for modules in the job conf but not in the modules list
        extra_modules = list(set(self._all["modules"]) - set(modules))
        for module_name in extra_modules:
            del self._all["modules"][module_name]
        # Write to a file
        with open(path, "w") as wf:
            wf.write(yaml.dump(self._all, default_flow_style=False))

    def has_key(self, key):
        present = key in self._all
        return present

    def get_val(self, key):
        if key in self._all:
            val = self._all[key]
        else:
            val = None
        return val

    def get_all_conf(self):
        return self._all

    def get_module_conf(self, module_name, module_type=None):
        if module_name not in self._modules:
            self._load_module_conf(module_name)
        if "modules" in self._all and module_name in self._all["modules"]:
            return self._all["modules"][module_name]
        else:
            return None

    def get_cravat_conf(self):
        if "cravat" not in self._all:
            self._load_main_conf()
        return self._all["cravat"]

    def get_system_conf(self):
        if "system" not in self._all:
            self._load_system_conf()
        return self._all["system"]

    def get_modules_conf(self):
        conf = self._all.get("modules", {})
        return conf

    def get_cravat_conf_value(self, key):
        if "cravat" in self._all:
            if key in self._all["cravat"]:
                return self._all["cravat"][key]
            else:
                return None
        else:
            return None

    def override_run_conf(self, run_conf):
        from .admin_util import recursive_update

        self._all["run"] = recursive_update(self._all["run"], run_conf)

    def override_cravat_conf(self, cravat_conf):
        from .admin_util import recursive_update

        self._all["cravat"] = recursive_update(self._all["cravat"],
                                               cravat_conf)

    def override_all_conf(self, conf):
        from .admin_util import recursive_update

        self._all = recursive_update(self._all, conf)

    def get_local_module_confs(self):
        return self._all["modules"]

    def get_run_conf(self):
        return self._all["run"]
