"""Headless probe: load live2d/index.html in QWebEngine and verify the model loaded.

Captures console.log/warn/error from the page so loading errors surface in PowerShell.
Picks up the active model from config.example.yaml via core.live2d_config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.live2d_config import Live2DConfig  # noqa: E402

LEVELS = {
    QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "INFO ",
    QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN ",
    QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "ERROR",
}


class LoggingPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        lvl = LEVELS.get(level, str(level))
        print(f"[js {lvl}] {Path(source).name}:{line}  {message}")


def main() -> int:
    app = QApplication(sys.argv)
    view = QWebEngineView()
    page = LoggingPage(view)
    view.setPage(page)
    view.resize(800, 600)
    settings = view.settings()
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True
    )
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    l2d = Live2DConfig.from_app_config(cfg)
    print(f"[probe] active model: {l2d.model_dir.name}")
    print(f"[probe] model_file:   {l2d.model_file}")
    print(f"[probe] emotion_mapping entries: {len(l2d.emotion_mapping)}")

    html_path = Path("live2d/index.html").resolve()
    url = QUrl.fromLocalFile(str(html_path))
    url.setQuery(
        f"model={l2d.model_url_path}&fit={l2d.fit_mode}&mouth={l2d.lip_sync_param}"
    )
    view.load(url)
    view.show()

    def make_callback(label, finalize=False):
        def cb(r):
            print(f"[probe {label}] -> {r!r}")
            if finalize:
                QTimer.singleShot(300, app.quit)
        return cb

    def step1():
        page.runJavaScript(
            "JSON.stringify({"
            "  pixi: typeof window.PIXI,"
            "  pixi_live2d: typeof (window.PIXI && window.PIXI.live2d),"
            "  cubism_core: typeof window.Live2DCubismCore,"
            "  status: (document.getElementById('status') || {}).textContent"
            "})",
            make_callback("libs"),
        )

    def step2():
        page.runJavaScript(
            "JSON.stringify(window.imouto && window.imouto.info ? "
            "{state:'loaded', info: window.imouto.info()} : "
            "{state:'not_loaded', status:(document.getElementById('status')||{}).textContent})",
            make_callback("model", finalize=True),
        )

    QTimer.singleShot(1500, step1)
    QTimer.singleShot(7000, step2)
    QTimer.singleShot(11000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
