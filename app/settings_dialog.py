from __future__ import annotations

from core.i18n import tf, tr
import keyring
from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ai.client import AISettings, OpenAICompatibleClient

SERVICE_NAME = "PhysicsExperiment.SoundWavAnalyzer"

# 新装默认 120 s：DeepSeek-R1 一类推理模型的首字延迟常常超过 60 s，
# 原来的 60 s 默认值让用户频繁遇到超时。键名带 _v2 是为了让老配置里
# 已经写死的 60 s 不再生效——否则改默认值对升级用户没有任何作用。
DEFAULT_TIMEOUT_S = 120.0
TIMEOUT_SETTINGS_KEY = "ai/timeout_v2"
TIMEOUT_MAX_S = 600.0

# 预设厂商：选预设时 Base URL 与常用模型名自动填好，用户只需填 API Key。
# 模型下拉框可编辑，仍允许填写厂家的其它模型名。
VENDOR_PRESETS: dict[str, dict] = {
    "DeepSeek（深度求索）": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "key_hint": tr("在 platform.deepseek.com 的 API keys 页面创建，形如 sk-…"),
    },
    "Moonshot（月之暗面 Kimi）": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-latest", "kimi-k2-0905-preview", "moonshot-v1-32k", "moonshot-v1-8k"],
        "key_hint": tr("在 platform.moonshot.cn 的 API Key 管理页创建，形如 sk-…"),
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
        "key_hint": tr("在 platform.openai.com 的 API keys 页面创建，形如 sk-…"),
    },
}
CUSTOM_VENDOR = tr("自定义（自填 Base URL 与模型名）")

# 预设的「键」是稳定的中文字面量（QSettings 里存的也是它），只在显示时过 tr()。
# 千万不要拿 tr() 的返回值当字典键：英文模式下它已经变成 "DeepSeek"，查表必崩。
DEFAULT_VENDOR_KEY = "DeepSeek（深度求索）"


def _guess_vendor(base_url: str) -> str | None:
    """按 Base URL 反查预设键；不属于任何预设时返回 None，表示「自定义」。"""
    for name, preset in VENDOR_PRESETS.items():
        if preset["base_url"].rstrip("/") == base_url.strip().rstrip("/"):
            return name
    return None


def _load_timeout(stored: QSettings) -> float:
    value = stored.value(TIMEOUT_SETTINGS_KEY, None)
    if value is None:
        return DEFAULT_TIMEOUT_S
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_S


def load_ai_settings() -> AISettings:
    stored = QSettings()
    try:
        api_key = keyring.get_password(SERVICE_NAME, "default") or ""
    except Exception:
        api_key = ""
    return AISettings(
        base_url=stored.value("ai/base_url", VENDOR_PRESETS[DEFAULT_VENDOR_KEY]["base_url"]),
        model=stored.value("ai/model", ""),
        api_key=api_key,
        temperature=float(stored.value("ai/temperature", 0.2)),
        timeout_s=_load_timeout(stored),
    )


class _ConnectProbe(QThread):
    """在后台线程里发一次测试请求。

    "测试连接"原来直接在界面线程里同步等待网络，慢网或服务无响应时整个窗口
    会冻住（最长到超时那 120 s），用户连关都关不掉（BUG-007）。
    """

    done = Signal(str, str)  # ("ok" | "fail", 文本)

    def __init__(self, settings: AISettings, parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self) -> None:
        client = None
        try:
            client = OpenAICompatibleClient(self._settings)
            self.done.emit("ok", client.test_connection())
        except Exception as exc:  # noqa: BLE001 - 任何失败都要变成可读提示
            self.done.emit("fail", str(exc))
        finally:
            if client is not None:
                client.close()


class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("AI 模型设置"))
        self.setMinimumWidth(520)
        settings = load_ai_settings()

        self.vendor = QComboBox()
        # 显示名过 tr()、用户数据留原始键：英文界面显示 "DeepSeek"，存盘仍是稳定键
        for name in VENDOR_PRESETS:
            self.vendor.addItem(tr(name), name)
        self.vendor.addItem(CUSTOM_VENDOR, None)
        self.vendor.setCurrentIndex(
            max(0, self.vendor.findData(_guess_vendor(settings.base_url))))

        self.base_url = QLineEdit(settings.base_url)
        self.base_url.setPlaceholderText(tr("例如：https://api.deepseek.com/v1"))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        if settings.model:
            self.model.addItem(settings.model)
        self.model.setCurrentText(settings.model)

        self.api_key = QLineEdit(settings.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText(tr("仅保存在本机，不写入源码，也不随文件分发"))
        self.key_hint = QLabel("")
        self.key_hint.setWordWrap(True)
        self.key_hint.setStyleSheet("color:#607d8b;")

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setValue(settings.temperature)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(5, TIMEOUT_MAX_S)
        self.timeout.setSingleStep(10)
        self.timeout.setDecimals(0)
        self.timeout.setValue(settings.timeout_s)
        self.timeout.setSuffix(" s")
        self.timeout.setToolTip(
            tf('单次 HTTP 请求的等待上限。推理模型思考时间较长时调大一些；遇到“请求超时”先试 {_v0} s 以上。', _v0=(int(DEFAULT_TIMEOUT_S))))

        # 这里不再提供“是否用钥匙串保存”的勾选框：不勾就存不下 Key，
        # 用户只能反复重填。改为固定声明 Key 的保存方式与用途。
        self.key_store_note = QLabel(
            tr("API Key 由 Windows 系统钥匙串（凭据管理器）加密保存，仅存在本机，"
            "不写入配置文件、不写入日志、也不随本程序分发。")
        )
        self.key_store_note.setWordWrap(True)
        self.key_store_note.setStyleSheet("color:#455a64;")

        self.privacy_note = QLabel(
            tr("WAV Analyzer 不会向任何人透露 API Key。"
            "Key 只在与你填写的 Base URL 通信时放入请求头，"
            "其它任何网络请求都不会携带它；导出的 TXT、CSV、图片与报告也不含 Key。")
        )
        self.privacy_note.setWordWrap(True)
        self.privacy_note.setStyleSheet(
            "color:#1f5b38;background:#e9f4ec;border:1px solid #c8e0d2;"
            "border-radius:4px;padding:7px;")

        self.vendor_note = QLabel(
            tr("选择预设厂商后，Base URL 与模型名会自动填好，只需填写 API Key；"
            "选择“自定义”则三项都要自己填。模型名可手动改写为厂家的其它模型。")
        )
        self.vendor_note.setWordWrap(True)
        self.vendor_note.setStyleSheet("color:#455a64;")

        form = QFormLayout()
        form.addRow(tr("厂商预设"), self.vendor)
        form.addRow("Base URL", self.base_url)
        form.addRow(tr("模型名称"), self.model)
        form.addRow("API Key", self.api_key)
        form.addRow("", self.key_hint)
        form.addRow(tr("温度"), self.temperature)
        form.addRow(tr("超时"), self.timeout)

        test_button = QPushButton(tr("测试连接"))
        test_button.clicked.connect(self.test_connection)
        self.test_button = test_button
        self._probe: _ConnectProbe | None = None
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("保存"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(test_button)
        row.addStretch()
        row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.vendor_note)
        layout.addLayout(form)
        layout.addWidget(self.key_store_note)
        layout.addWidget(self.privacy_note)
        layout.addLayout(row)

        self.vendor.currentIndexChanged.connect(self._apply_vendor)
        self._apply_vendor(keep_model=True)

    # ------------------------------------------------------------ 厂商预设
    def _apply_vendor(self, *_: object, keep_model: bool = False) -> None:
        """按当前选中的预设键填 Base URL 与模型名；自定义项的键是 None。"""
        preset = VENDOR_PRESETS.get(self.vendor.currentData())
        if preset is None:
            self.base_url.setReadOnly(False)
            self.base_url.setStyleSheet("")
            self.key_hint.setText(tr("自定义服务需兼容 OpenAI 的 /chat/completions 与 /models 接口。"))
            return
        self.base_url.setText(preset["base_url"])
        self.base_url.setReadOnly(True)
        self.base_url.setStyleSheet("color:#455a64;background:#f1f3f4;")
        current = self.model.currentText().strip()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(preset["models"])
        if keep_model and current:
            self.model.setCurrentText(current)
        else:
            self.model.setCurrentText(preset["models"][0])
        self.model.blockSignals(False)
        self.key_hint.setText(preset["key_hint"])

    def settings(self) -> AISettings:
        return AISettings(
            self.base_url.text().strip(), self.model.currentText().strip(),
            self.api_key.text().strip(), self.temperature.value(), self.timeout.value(),
        )

    def test_connection(self) -> None:
        if self._probe is not None:
            return
        self.test_button.setEnabled(False)
        self.test_button.setText(tr("正在测试…"))
        probe = _ConnectProbe(self.settings(), self)
        probe.done.connect(self._probe_finished)
        probe.finished.connect(probe.deleteLater)
        self._probe = probe
        probe.start()

    def _probe_finished(self, kind: str, message: str) -> None:
        self._probe = None
        self.test_button.setEnabled(True)
        self.test_button.setText(tr("测试连接"))
        if kind == "ok":
            QMessageBox.information(self, tr("连接测试"), message)
        else:
            QMessageBox.warning(
                self, tr("连接失败"),
                tf('{exc}\n\n请依次检查：API Key 是否正确、Base URL 是否可用、模型名是否存在。',
                   exc=(message)))

    def accept(self) -> None:
        base_url = self.base_url.text().strip()
        model = self.model.currentText().strip()
        if not base_url or not model:
            QMessageBox.warning(self, tr("设置不完整"), tr("Base URL 和模型名称不能为空。"))
            return
        if not self.api_key.text().strip():
            answer = QMessageBox.question(
                self, tr("未填写 API Key"),
                tr("当前未填写 API Key，AI 助手调用会被服务端拒绝。是否仍然保存？"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        stored = QSettings()
        stored.setValue("ai/base_url", base_url)
        stored.setValue("ai/model", model)
        stored.setValue("ai/vendor", self.vendor.currentData() or "")
        stored.setValue("ai/temperature", self.temperature.value())
        stored.setValue(TIMEOUT_SETTINGS_KEY, self.timeout.value())
        # Key 只有钥匙串一条保存路径，没有“写进注册表”的退路，
        # 这样它永远不会出现在 QSettings 的明文 ini 里。
        key = self.api_key.text().strip()
        key_note = ""
        try:
            if key:
                keyring.set_password(SERVICE_NAME, "default", key)
            elif keyring.get_password(SERVICE_NAME, "default"):
                keyring.delete_password(SERVICE_NAME, "default")
        except Exception as exc:
            key_note = tf('\n\n⚠ Key 未能写入 Windows 钥匙串：{exc}\n下次启动需要重新填写。', exc=(exc))
        if key_note:
            QMessageBox.warning(self, tr("钥匙串不可用"), tr("其余设置已保存。") + key_note)
        # 保存后立刻读回一次：写盘失败（目录只读、设置文件被占用）时，
        # 不能让用户以为已经存好了，否则下次打开又回到「未填写」。
        saved = load_ai_settings()
        lost = []
        if saved.model.strip() != model:
            lost.append(tr("模型名称"))
        if saved.base_url.strip() != base_url:
            lost.append("Base URL")
        if lost:
            QMessageBox.warning(
                self, tr("设置没有存住"),
                tf('{_v0} 没能写入设置文件：{_v1}\n\n请把程序放到可写目录后再保存。',
                   _v0=("、".join(lost)), _v1=(str(QSettings().fileName()))))
        super().accept()
