use crate::config::CLIPBOARD_CRLF;

pub fn normalize_for_clipboard(text: &str) -> String {
    if !CLIPBOARD_CRLF {
        return text.to_string();
    }
    #[cfg(target_os = "windows")]
    {
        text.replace("\r\n", "\n")
            .replace('\r', "\n")
            .replace('\n', "\r\n")
    }
    #[cfg(not(target_os = "windows"))]
    {
        text.replace("\r\n", "\n").replace('\r', "\n")
    }
}
