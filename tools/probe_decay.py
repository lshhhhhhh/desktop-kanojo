"""Verify expression decay: set an expression, wait, confirm it cleared."""

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


def main() -> int:
    app = QApplication(sys.argv)
    view = QWebEngineView()
    page = QWebEnginePage(view)
    view.setPage(page)
    view.resize(600, 600)
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Use a snappy 2-second decay for the probe instead of the configured 8s
    cfg.setdefault("live2d", {})["expression_decay_seconds"] = 2
    l2d = Live2DConfig.from_app_config(cfg)
    print(f"[probe] decay window: {int(l2d.expression_decay_seconds * 1000)} ms")

    html_path = Path("live2d/index.html").resolve()
    url = QUrl.fromLocalFile(str(html_path))
    url.setQuery(
        f"model={l2d.model_url_path}&fit={l2d.fit_mode}"
        f"&mouth={l2d.lip_sync_param}&decay=2000"
    )
    view.load(url)
    view.show()

    def label_cb(label):
        def cb(r):
            print(f"  [{label}] {r}")
        return cb

    def at_2000_set():
        print("[t=2.0s] setExpression(0)  — expect decayPending=True afterwards")
        page.runJavaScript(
            "window.imouto.setExpression(0); JSON.stringify({decayPending: window.imouto.info().decayPending})",
            label_cb("after setExpression"),
        )

    def at_3000_during():
        # 1s into a 2s decay window → still pending
        page.runJavaScript(
            "JSON.stringify({decayPending: window.imouto.info().decayPending})",
            label_cb("t=3.0s during decay (expect True)"),
        )

    def at_5000_after():
        # 3s after setExpression, decay was 2s → should have fired
        page.runJavaScript(
            "JSON.stringify({decayPending: window.imouto.info().decayPending})",
            label_cb("t=5.0s after decay fired (expect False)"),
        )
        QTimer.singleShot(500, app.quit)

    QTimer.singleShot(2000, at_2000_set)
    QTimer.singleShot(3000, at_3000_during)
    QTimer.singleShot(5000, at_5000_after)
    QTimer.singleShot(7000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
