"""Optional AI face restoration (GFPGAN 1.4) before mapping.

Faces in a photo are often only ~100 px across, and 0.2 mm pixels keep about
that many, so eyes and teeth blur. GFPGAN redraws each face sharper at 512 px;
we paste it back with a soft edge. It can change a face slightly, so it is off
by default. Plain upscaling adds nothing: the print can't hold more pixels.

Needs `pip install layertone[faces]` (onnxruntime, opencv). The models (~350 MB)
download once into ~/.cache/layertone from the FaceFusion asset releases:
yoloface_8n finds faces and 5 landmarks, gfpgan_1.4 restores them.
"""
from pathlib import Path
import urllib.request
import numpy as np

CACHE = Path.home() / ".cache" / "layertone"
URL = "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/"
# eyes, nose, mouth corners of an aligned 512 px face (FFHQ layout)
TEMPLATE = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                     [0.39308822, 0.72541100], [0.61150205, 0.72490465]], np.float32) * 512


def _model(name):
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} (once)...")
        urllib.request.urlretrieve(URL + name, path.with_suffix(".part"))
        path.with_suffix(".part").rename(path)
    import onnxruntime as ort
    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def detect(bgr, threshold=0.25):
    """[(box x,y,w,h, landmarks (5,2), score)] in image pixels."""
    import cv2
    h, w = bgr.shape[:2]
    s = 640 / max(h, w)
    pad = np.zeros((640, 640, 3), np.uint8)
    pad[:round(h * s), :round(w * s)] = cv2.resize(bgr, (round(w * s), round(h * s)))
    x = ((pad.astype(np.float32) - 127.5) / 128).transpose(2, 0, 1)[None]
    out = _model("yoloface_8n.onnx").run(None, {"input": x})[0][0].T
    out = out[out[:, 4] > threshold]
    boxes = np.stack([out[:, 0] - out[:, 2] / 2, out[:, 1] - out[:, 3] / 2, out[:, 2], out[:, 3]], 1)
    keep = np.array(cv2.dnn.NMSBoxes(boxes.tolist(), out[:, 4].tolist(), threshold, 0.4)).flatten()
    return [(boxes[i] / s, out[i, 5:].reshape(5, 3)[:, :2] / s, float(out[i, 4])) for i in keep]


def restore_faces(img, strength=1.0):
    """PIL RGB image -> PIL RGB image with every detected face restored."""
    import cv2
    from PIL import Image
    bgr = np.asarray(img.convert("RGB"))[:, :, ::-1].copy()
    gfpgan = _model("gfpgan_1.4.onnx")
    H, W = bgr.shape[:2]
    res = bgr.astype(np.float32)
    edge = np.zeros((512, 512), np.float32)
    edge[40:-40, 40:-40] = 1
    edge = cv2.GaussianBlur(edge, (0, 0), 20)
    for _, kps, _ in detect(bgr):
        A, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), TEMPLATE, method=cv2.LMEDS)
        crop = cv2.warpAffine(bgr, A, (512, 512), borderMode=cv2.BORDER_REPLICATE)
        x = ((crop[:, :, ::-1] / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None].astype(np.float32)
        y = gfpgan.run(None, {"input": x})[0][0].transpose(1, 2, 0).clip(-1, 1)
        y = ((y + 1) * 127.5)[:, :, ::-1].astype(np.float32)
        Ai = cv2.invertAffineTransform(A)
        m = cv2.warpAffine(edge, Ai, (W, H))[..., None] * strength
        res = res * (1 - m) + cv2.warpAffine(y, Ai, (W, H)) * m
    return Image.fromarray(res.clip(0, 255).astype(np.uint8)[:, :, ::-1])
