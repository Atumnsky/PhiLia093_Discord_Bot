import aiohttp
import base64
import traceback
from io import BytesIO
from PIL import Image
from config import ALIYUN_API_KEY

async def compress_image_to_size(
    image_bytes: bytes,
    target_size_mb: float = 4.5,
    max_pixels: int = 1024,      # 长边最大像素
    initial_quality: int = 95    # 起始 JPEG 质量（更高）
) -> bytes:
    """等比缩放至长边≤max_pixels，然后调整 JPEG 质量至目标大小。失败返回原图。"""
    try:
        img = Image.open(BytesIO(image_bytes))
        # 统一转为 RGB（防止 RGBA 或 P 模式无法保存为 JPEG）
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # 1. 等比缩放（长边≤max_pixels）
        img.thumbnail((max_pixels, max_pixels), Image.Resampling.LANCZOS)

        # 2. 循环调整质量
        quality = initial_quality
        output = BytesIO()
        while quality >= 10:
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=quality)
            if len(output.getvalue()) <= target_size_mb * 1024 * 1024:
                return output.getvalue()
            quality -= 5  # 步长可调（更精细的控制）
        # 如果最低质量仍不满足，返回最后一次结果（已尽力）
        return output.getvalue()
    except Exception as e:
        print(f"[Image] Compression failed: {e}")
        traceback.print_exc()
        return image_bytes  # 失败回退原图

async def describe_image(image_bytes: bytes, user_prompt: str = "Please briefly describe...") -> str:
    if not ALIYUN_API_KEY:
        return "ALIYUN_API_KEY not set."

    try:
        # 压缩图片（你的 compress_image_to_size 保持不变）
        compressed = await compress_image_to_size(image_bytes, target_size_mb=4.5)
        print(f"[Image] Compressed: {len(image_bytes)} -> {len(compressed)} bytes")

        base64_image = base64.b64encode(compressed).decode('utf-8')
        image_uri = f"data:image/jpeg;base64,{base64_image}"

        # 兼容模式的消息体
        payload = {
            "model": "qwen3-vl-plus",  # 或 qwen3.6-plus
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_uri}
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ],
            # 按需可选参数，如生成图片尺寸等不需要
        }

        headers = {
            "Authorization": f"Bearer {ALIYUN_API_KEY}",
            "Content-Type": "application/json"
        }

        # 使用兼容模式端点
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"[Image] HTTP {resp.status}: {error_text}")
                    return f"Image recognition failed (HTTP {resp.status})."
                data = await resp.json()
                # 直接提取文本内容
                content = data["choices"][0]["message"]["content"]
                return content

    except Exception as e:
        print(f"[Image] describe_image error: {e}")
        traceback.print_exc()
        return f"Error: {str(e)}"

async def generate_image(prompt: str, n: int = 1) -> list:
    """使用阿里云 qwen-image-2.0 生成图片，返回图片 URL 列表"""
    if not ALIYUN_API_KEY:
        print("ALIYUN_API_KEY not set")
        return []

    try:
        payload = {
            "model": "qwen-image-2.0-pro",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ]
            },
            "parameters": {
                "negative_prompt": "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。",
                "size": "2688*1536",
                "n": n
            }
        }

        headers = {
            "Authorization": f"Bearer {ALIYUN_API_KEY}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"[Image Gen] API error {resp.status}: {error_text}")
                    return []
                data = await resp.json()
                urls = []
                if "output" in data and "choices" in data["output"]:
                    content = data["output"]["choices"][0]["message"]["content"]
                    for item in content:
                        if "image" in item:
                            urls.append(item["image"])
                return urls
    except Exception as e:
        print(f"[Image Gen] error: {e}")
        return []

async def edit_image(image_bytes: bytes, instruction: str) -> list:
    """使用阿里云 qwen-image-2.0 编辑图片，返回图片 URL 列表"""
    if not ALIYUN_API_KEY:
        print("ALIYUN_API_KEY not set")
        return []

    try:
        compressed = await compress_image_to_size(image_bytes, target_size_mb=4.5)
        base64_image = base64.b64encode(compressed).decode('utf-8')
        image_uri = f"data:image/jpeg;base64,{base64_image}"

        payload = {
            "model": "qwen-image-2.0-pro",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": image_uri},
                            {"text": instruction}
                        ]
                    }
                ]
            },
            "parameters": {}
        }

        headers = {
            "Authorization": f"Bearer {ALIYUN_API_KEY}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"[Image Edit] API error {resp.status}: {error_text}")
                    return []
                data = await resp.json()
                urls = []
                if "output" in data and "choices" in data["output"]:
                    content = data["output"]["choices"][0]["message"]["content"]
                    for item in content:
                        if "image" in item:
                            urls.append(item["image"])
                return urls
    except Exception as e:
        print(f"[Image Edit] error: {e}")
        return []