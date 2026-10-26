"""Model connection editor."""

from urllib.parse import urlparse

from nicegui import ui

from core.i18n import t
from service.chat import model_providers as models


def render_model_settings():
    ui.label(t("模型配置")).classes("text-xs font-medium text-gray-400 pb-2")
    provider = ui.select({key: t(value[0]) for key, value in models.PROVIDERS.items()}, value="deepseek", label=t("服务商")).props("outlined dense hide-bottom-space").classes("w-full")

    @ui.refreshable
    def editor():
        name = provider.value
        connection = models.load()["connections"].get(name, {})
        key = ui.input(label="API Key", value=connection.get("key", ""), password=True, password_toggle_button=True).props("outlined dense hide-bottom-space").classes("w-full mt-3")
        endpoint = ui.input(label=t("API 地址"), value=connection.get("base_url", models.PROVIDERS[name][1])).props("outlined dense hide-bottom-space").classes("w-full mt-3")
        entries = ui.textarea(label=t("启用模型（每行一个模型 ID 或固定版本 ID）"), value="\n".join(connection.get("models", []))).props("outlined dense autogrow hide-bottom-space").classes("w-full mt-3")
        if name == "qwen":
            ui.label(t("API 地址需与密钥地域一致：北京 dashscope.aliyuncs.com；新加坡 dashscope-intl.aliyuncs.com。保留 /compatible-mode/v1 后缀。")).classes("text-xs text-gray-500 mt-2")

        async def fetch_models():
            import httpx
            if not (key.value or "").strip():
                ui.notify(t("请先填写 API Key"), type="warning")
                return
            fetch.disable()
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
                fetch.enable()

        async def save():
            import httpx
            enabled = list(dict.fromkeys(line.strip() for line in (entries.value or "").splitlines() if line.strip()))
            address = (endpoint.value or "").strip().rstrip("/")
            parsed = urlparse(address)
            if not key.value.strip() or not enabled or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                ui.notify(t("请填写密钥、HTTPS API 地址和至少一个模型"), type="warning")
                return
            connection_data = {"key": key.value.strip(), "base_url": address, "models": enabled}
            save_button.disable()
            try:
                await models.validate_connection(name, connection_data)
            except (ValueError, httpx.HTTPError) as error:
                ui.notify(str(error) if isinstance(error, ValueError) else t("连接验证失败，请检查网络后重试"), type="warning")
                return
            finally:
                save_button.enable()
            data = models.load()
            data["connections"][name] = connection_data
            models.save(data)
            ui.notify(t("模型连接已保存"), type="positive")

        with ui.row().classes("w-full justify-end gap-2 pt-3"):
            fetch = ui.button(t("获取模型"), icon="refresh", on_click=fetch_models).props("flat dense")
            save_button = ui.button(t("验证并保存"), on_click=save).props("dense")

    provider.on_value_change(lambda _: editor.refresh())
    with ui.column().classes("w-full gap-0") as container:
        editor()
