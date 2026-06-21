from __future__ import annotations

import os
from typing import Dict, List

import numpy as np


class YOLODetector:
    def __init__(self, onnx_path: str = "", confidence: float = 0.35, gpu: bool = False):
        self.onnx_path = onnx_path
        self.confidence = float(confidence)
        self.gpu = bool(gpu)
        self.session = None
        self.input_name = None
        self.input_shape = None
        if onnx_path and os.path.exists(onnx_path):
            try:
                import onnxruntime as ort

                providers = (
                    ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    if self.gpu
                    else ["CPUExecutionProvider"]
                )
                self.session = ort.InferenceSession(onnx_path, providers=providers)
                inputs = self.session.get_inputs()
                self.input_name = inputs[0].name
                self.input_shape = list(inputs[0].shape)
            except Exception:
                self.session = None
                self.input_name = None
                self.input_shape = None

    def is_available(self) -> bool:
        return self.session is not None

    def detect(self, frame: np.ndarray) -> List[Dict]:
        if not self.is_available() or frame is None or frame.size == 0:
            return []
        try:
            import cv2

            in_h, in_w = self._input_size()
            ih, iw = frame.shape[:2]
            img = cv2.resize(frame, (in_w, in_h))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)[None, ...]
            outputs = self.session.run(None, {self.input_name: img})
            return self._postprocess(outputs[0], in_w, in_h, iw, ih)
        except Exception:
            return []

    def _input_size(self):
        shape = self.input_shape or [1, 3, 640, 640]
        h = shape[-2] if len(shape) >= 2 and isinstance(shape[-2], int) else 640
        w = shape[-1] if len(shape) >= 1 and isinstance(shape[-1], int) else 640
        return int(h), int(w)

    def _postprocess(self, output, in_w, in_h, ow, oh) -> List[Dict]:
        preds = np.asarray(output)
        if preds.ndim == 3:
            preds = preds[0]
        if preds.ndim != 2 or preds.shape[0] < 4:
            return []
        if preds.shape[0] <= preds.shape[1]:
            preds = preds.T
        boxes = preds[:, :4].astype(np.float32)
        scores = preds[:, 4:]
        if scores.size == 0:
            return []
        class_ids = np.argmax(scores, axis=1)
        confs = np.max(scores, axis=1)
        mask = confs >= self.confidence
        boxes = boxes[mask]
        class_ids = class_ids[mask]
        confs = confs[mask]
        keep = self._nms(boxes, confs)
        sx = ow / float(in_w)
        sy = oh / float(in_h)
        results: List[Dict] = []
        for k in keep:
            cx, cy, bw, bh = boxes[k]
            x = (cx - bw / 2.0) * sx
            y = (cy - bh / 2.0) * sy
            w = bw * sx
            h = bh * sy
            results.append(
                {
                    "class_name": f"class_{int(class_ids[k])}",
                    "confidence": float(confs[k]),
                    "bbox": [float(x), float(y), float(w), float(h)],
                }
            )
        return results

    def _nms(self, boxes_xywh, scores, iou_threshold: float = 0.45) -> List[int]:
        if len(boxes_xywh) == 0:
            return []
        cx = boxes_xywh[:, 0]
        cy = boxes_xywh[:, 1]
        bw = boxes_xywh[:, 2]
        bh = boxes_xywh[:, 3]
        x1 = cx - bw / 2.0
        y1 = cy - bh / 2.0
        x2 = cx + bw / 2.0
        y2 = cy + bh / 2.0
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep: List[int] = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            union = areas[i] + areas[order[1:]] - inter
            iou = inter / np.maximum(union, 1e-9)
            idx = np.where(iou <= iou_threshold)[0]
            order = order[idx + 1]
        return keep
