"""Model connection editor."""

from urllib.parse import urlparse

from nicegui import ui

from core.i18n import t
from component.action_button import action_button
from service.chat import model_providers as models


class ModelDrafts:
    """Window-local edits; never persist unvalidated credentials."""

    def __init__(self):
        self.provider = "deepseek"
        self.values = {}
        self.baselines = {}
        self.busy = False

    def get(self, name):
        if name not in self.values:
            connection = models.load()["connections"].get(name, {})
            self.values[name] = {
                "key": connection.get("key", ""),
                "base_url": connection.get("base_url", models.PROVIDERS[name][1]),
                "models": "\n".join(connection.get("models", [])),
                "vision_models": "\n".join(connection.get("vision_models", [])),
            }
            self.baselines[name] = self.values[name].copy()
        return self.values[name]

    def dirty(self):
        return any(value != self.baselines[name] for name, value in self.values.items())


def window_drafts(client):
    if not hasattr(client, "calabash_model_drafts"):
        client.calabash_model_drafts = ModelDrafts()
    return client.calabash_model_drafts


async def confirm_settings_leave(client, *, reload=False):
    state = window_drafts(client)
    if state.busy:
        with client.layout:
            ui.notify(t("正在验证连接，请稍候"), type="info")
        return False
    if not state.dirty():
        return True
    with client.layout, ui.dialog() as dialog, ui.card().classes("w-96 max-w-full gap-4"):
        ui.label(t("有未保存的模型设置")).classes("text-base font-semibold")
        ui.label(t("切换语言将丢弃当前窗口的草稿。") if reload else t("草稿仅保留在当前窗口，返回设置可继续编辑。")).classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("继续编辑"), on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(t("丢弃草稿并切换") if reload else t("保留草稿并离开"), on_click=lambda: dialog.submit(True))
    return bool(await dialog)


def render_model_settings():
    client = ui.context.client
    state = window_drafts(client)
    ui.label(t("模型配置")).classes("app-section-title pb-3")
    provider = ui.select({key: t(value[0]) for key, value in models.PROVIDERS.items()}, value=state.provider, label=t("服务商")).props("outlined dense hide-bottom-space").classes("w-full")

    @ui.refreshable
    def editor():
        name = provider.value
        draft = state.get(name)
        key = ui.input(label="API Key", value=draft["key"], password=True, password_toggle_button=True).props("outlined dense hide-bottom-space").classes("w-full mt-3")
        endpoint = ui.input(label=t("API 地址"), value=draft["base_url"]).props("outlined dense hide-bottom-space").classes("w-full mt-3")
        entries = ui.textarea(label=t("启用模型（每行一个模型 ID 或固定版本 ID）"), value=draft["models"]).props("outlined dense autogrow hide-bottom-space").classes("w-full mt-3")
        if name == "qwen":
            ui.label(t("API 地址需与密钥地域一致：北京 dashscope.aliyuncs.com；新加坡 dashscope-intl.aliyuncs.com。保留 /compatible-mode/v1 后缀。")).classes("text-xs text-gray-500 mt-2")

        vision = ui.textarea(label=t('额外支持图片的模型 ID（每行一个，选填）'), value=draft["vision_models"]).props('outlined dense autogrow hide-bottom-space').classes('w-full mt-3')
        for field, control in (("key", key), ("base_url", endpoint), ("models", entries), ("vision_models", vision)):
            control.bind_value(draft, field)
        ui.label(t("草稿仅保留在当前窗口，返回设置可继续编辑。")).classes("text-xs text-gray-500 mt-2")

        ui.label(t('常见视觉模型自动识别；自定义模型可在此声明图片能力。')).classes('text-xs text-gray-500 mt-1')

        async def fetch_models():
            import httpx
            if not (key.value or "").strip():
                ui.notify(t("请先填写 API Key"), type="warning")
                return
            state.busy = True
            controls = (key, endpoint, entries, vision, provider, fetch, save_button)
            for control in controls:
                control.disable()
            try:
                available = await models.available_models(name, {"key": key.value.strip(), "base_url": endpoint.value})
                if not available:
                    ui.notify(t("未返回模型，可手动填写模型 ID"), type="info")
                    return
                # Keep selection explicit; fetching must not enable every model.
                with container:
                    with ui.dialog() as dialog, ui.card().classes("w-96 max-w-full gap-3"):
                        ui.label(t("选择启用模型")).classes("text-base font-semibold")
                        current = [line.strip() for line in entries.value.splitlines() if line.strip()]
                        options = list(dict.fromkeys([*current, *available]))
                        selection = ui.select(options, value=current, multiple=True, with_input=True).props("outlined dense use-chips").classes("w-full")
                        def apply():
                            entries.set_value("\n".join(selection.value or []))
                            dialog.close()
                        ui.button(t("应用"), on_click=apply)
                    dialog.open()
            except (httpx.HTTPError, ValueError, KeyError):
                ui.notify(t("获取失败，请检查密钥和 API 地址，也可手动填写模型 ID"), type="warning")
            finally:
                state.busy = False
                for control in controls:
                    control.enable()

        async def save():
            import httpx
            enabled = list(dict.fromkeys(line.strip() for line in (entries.value or "").splitlines() if line.strip()))
            address = (endpoint.value or "").strip().rstrip("/")
            parsed = urlparse(address)
            if not key.value.strip() or not enabled or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                ui.notify(t("请填写密钥、HTTPS API 地址和至少一个模型"), type="warning")
                return
            connection_data = {"key": key.value.strip(), "base_url": address, "models": enabled, "vision_models": [value.strip() for value in vision.value.splitlines() if value.strip() in enabled]}
            state.busy = True
            controls = (key, endpoint, entries, vision, provider, fetch, save_button)
            for control in controls:
                control.disable()
            try:
                await models.validate_connection(name, connection_data)
            except (ValueError, httpx.HTTPError) as error:
                ui.notify(str(error) if isinstance(error, ValueError) else t("连接验证失败，请检查网络后重试"), type="warning")
                return
            finally:
                state.busy = False
                for control in controls:
                    control.enable()
            data = models.load()
            data["connections"][name] = connection_data
            models.save(data)
            state.baselines[name] = draft.copy()
            ui.notify(t("模型连接已保存"), type="positive")

        with ui.row().classes("w-full justify-end gap-2 pt-3"):
            fetch, _ = action_button("refresh", t("获取模型"), fetch_models, text=True)
            save_button = ui.button(t("验证并保存"), on_click=save).props("dense")

    switching = {"active": False}

    async def switch_provider(event):
        if switching["active"] or event.value == state.provider:
            return
        switching["active"] = True
        target = event.value
        try:
            if not await confirm_settings_leave(client):
                provider.set_value(state.provider)
                return
            state.provider = target
            editor.refresh()
        finally:
            switching["active"] = False

    provider.on_value_change(switch_provider)
    with ui.column().classes("w-full gap-0") as container:
        editor()
