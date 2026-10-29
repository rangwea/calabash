"""Validated local image references; pixel bytes exist only in UI/wire payloads."""
import base64
import copy
import io
import os
import re
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_IMAGES = 5
PREFIX = 'calabash-image:'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def is_image(name):
    return Path(name).suffix.lower() in EXTENSIONS


def _decode(data, edge):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'} or source.width * source.height > MAX_PIXELS:
                    raise ValueError('invalid_image')
                source.seek(0)
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image.thumbnail((edge, edge))
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                output = io.BytesIO()
                background.save(output, format='PNG')
                mime = 'image/png'
                if len(output.getvalue()) > 3 * 1024 * 1024:
                    output = io.BytesIO()
                    background.save(output, format='JPEG', quality=85)
                    mime = 'image/jpeg'
                return mime, output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('invalid_image') from error


def validate(path, size):
    if size > MAX_BYTES:
        raise ValueError('image_limit')
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('image_limit')
    _decode(data, 96)


def encode(chat_id, file_id, *, thumbnail=False):
    from service.files import conversation_files as files
    from service.files.file_readers import authorized_record
    record = files.get_record(chat_id, file_id) if thumbnail else authorized_record(chat_id, file_id)
    if not record or not is_image(record['name']) or files.check(chat_id, file_id) != 'ready':
        raise ValueError('image_unavailable')
    if record['size'] > MAX_BYTES:
        raise ValueError('image_limit')
    fd = os.open(record['path'], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (record['device'], record['inode'], record['size'], record['mtime_ns']):
            raise ValueError('image_unavailable')
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or files.check(chat_id, file_id) != 'ready':
        raise ValueError('image_unavailable')
    mime, content = _decode(data, 112 if thumbnail else 2048)
    if not thumbnail and not authorized_record(chat_id, file_id):
        raise ValueError('image_unavailable')
    return f'data:{mime};base64,' + base64.b64encode(content).decode('ascii')


def attach_references(messages, chat_id):
    """Keep at most the newest five images in retained history, without pixels."""
    from service.files import conversation_files as files
    result = copy.deepcopy(messages)
    remaining = MAX_IMAGES
    for message in reversed(result):
        if message['role'] != 'user':
            continue
        parts = []
        for file_id in message.get('attachments', []):
            record = files.get_record(chat_id, file_id)
            if record and is_image(record['name']):
                if remaining:
                    parts.append({'type': 'image_url', 'image_url': {'url': PREFIX + file_id}})
                    remaining -= 1
                else:
                    message['content'] += '\n[Earlier image pixels omitted. Ask to reattach if needed.]'
        if parts:
            message['content'] = [{'type': 'text', 'text': message['content']}, *parts]
    return result


def hydrate(messages, chat_id, provider, model, connection):
    from core.i18n import t
    from service.chat.model_providers import supports_images
    result = copy.deepcopy(messages)
    count = 0
    for message in result:
        if not isinstance(message.get('content'), list):
            continue
        for block in message['content']:
            if block.get('type') != 'image_url':
                continue
            if not supports_images(provider, model, connection):
                raise ValueError(t('当前模型不支持图片，请选择支持视觉的模型'))
            url = block.get('image_url', {}).get('url', '')
            if message['role'] != 'user' or not isinstance(url, str) or not re.fullmatch(PREFIX + r'[a-f0-9]{32}', url):
                raise ValueError(t('图片引用无效，请重新添加图片'))
            count += 1
            if count > MAX_IMAGES:
                raise ValueError(t('每次最多发送 5 张图片'))
            try:
                block['image_url']['url'] = encode(chat_id, url[len(PREFIX):])
            except (ValueError, OSError) as error:
                raise ValueError(t('图片不可用或已变化，请重新添加后发送')) from error
    return result
