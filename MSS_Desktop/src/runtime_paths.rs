use std::{
    env, fs,
    path::{Path, PathBuf},
};

pub struct RuntimePaths {
    pub code: PathBuf,
    pub data: PathBuf,
}

impl RuntimePaths {
    pub fn resolve() -> Result<Self, String> {
        let executable = env::current_exe().map_err(|error| error.to_string())?;
        let folder = executable
            .parent()
            .ok_or("MSS executable directory is unavailable")?;
        let development = folder.ancestors().find(|directory| {
            directory.join("Cargo.toml").is_file()
                && directory.join("MSS_Desktop/Cargo.toml").is_file()
                && directory.join("MSS_MCP/tools/mss_universal.py").is_file()
        });
        let code = env::var_os("MSS_RUNTIME_ROOT")
            .map(PathBuf::from)
            .or_else(|| {
                folder
                    .join("MSS_MCP/tools/mss_universal.py")
                    .is_file()
                    .then(|| folder.to_path_buf())
            })
            .or_else(|| development.map(Path::to_path_buf))
            .ok_or("MSS runtime files were not found next to the executable")?;
        if !code.is_absolute() || !code.join("MSS_MCP/tools/mss_universal.py").is_file() {
            return Err("MSS_RUNTIME_ROOT must identify the installed MSS runtime".into());
        }
        let data = env::var_os("MSS_DATA_ROOT")
            .map(PathBuf::from)
            .or_else(|| {
                development
                    .filter(|directory| *directory == code)
                    .map(Path::to_path_buf)
            })
            .or_else(|| {
                env::var_os("LOCALAPPDATA")
                    .map(|path| PathBuf::from(path).join("Makepad SandStudio"))
            })
            .ok_or("The MSS user data directory is unavailable")?;
        if !data.is_absolute() {
            return Err("MSS_DATA_ROOT must be an absolute path".into());
        }
        Ok(Self { code, data })
    }

    pub fn python(&self) -> Result<PathBuf, String> {
        if let Some(path) = env::var_os("MSS_DESKTOP_PYTHON") {
            let path = PathBuf::from(path);
            if path.is_absolute() && path.is_file() {
                return Ok(path);
            }
            return Err("MSS_DESKTOP_PYTHON must identify an installed Python executable".into());
        }
        let executable = if cfg!(windows) {
            "python.exe"
        } else {
            "python3"
        };
        env::var_os("PATH")
            .into_iter()
            .flat_map(|value| env::split_paths(&value).collect::<Vec<_>>())
            .filter(|path| path.is_absolute() && !path.ends_with("Microsoft/WindowsApps"))
            .map(|path| path.join(executable))
            .find(|path| path.is_file())
            .or_else(|| {
                env::var_os("USERPROFILE")
                    .map(|profile| {
                        PathBuf::from(profile).join(
                ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
            )
                    })
                    .filter(|path| path.is_file())
            })
            .ok_or_else(|| {
                "Install Python 3.12+ or set MSS_DESKTOP_PYTHON to its absolute executable path"
                    .into()
            })
    }

    pub fn proof(&self, name: &str) -> Result<PathBuf, String> {
        let path = self.data.join("proof").join(name);
        for ancestor in path.ancestors().collect::<Vec<_>>().into_iter().rev() {
            match fs::symlink_metadata(ancestor) {
                Ok(metadata) if metadata.is_dir() && !is_reparse(&metadata) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    match fs::create_dir(ancestor) {
                        Ok(()) => {}
                        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                        Err(error) => return Err(error.to_string()),
                    }
                    let metadata =
                        fs::symlink_metadata(ancestor).map_err(|error| error.to_string())?;
                    if !metadata.is_dir() || is_reparse(&metadata) {
                        return Err(
                            "MSS data directories must be local directories without reparse points"
                                .into(),
                        );
                    }
                }
                _ => {
                    return Err(
                        "MSS data directories must be local directories without reparse points"
                            .into(),
                    );
                }
            }
        }
        Ok(path)
    }
}

fn is_reparse(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}
