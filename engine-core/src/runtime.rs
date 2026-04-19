use std::path::Path;

/// Returns true when `path` exists (external kill switch file).
pub fn kill_switch_active(path: Option<&std::path::PathBuf>) -> bool {
    path.map(|p| Path::new(p).exists()).unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn kill_switch_triggers_when_file_present() {
        let tmp = std::env::temp_dir().join("algo_trader_kill_test");
        let _ = fs::remove_file(&tmp);
        assert!(!kill_switch_active(Some(&tmp)));
        fs::write(&tmp, b"1").unwrap();
        assert!(kill_switch_active(Some(&tmp)));
        let _ = fs::remove_file(&tmp);
    }
}
