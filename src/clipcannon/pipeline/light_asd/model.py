# ruff: noqa: N801, N802, N806, ANN001, ANN201, ANN202, ANN204, E501, TC003
"""Light-ASD network (vendored from Junhua-Liao/Light-ASD, MIT license).

Layer and attribute names match upstream exactly so the published weights
load without remapping. Training code is not included.
"""
from __future__ import annotations

from pathlib import Path

import torch
from torch import nn


class Audio_Block(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.relu = nn.ReLU()
        self.m_3 = nn.Conv2d(in_channels, out_channels, kernel_size=(3, 1), padding=(1, 0), bias=False)
        self.bn_m_3 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_3 = nn.Conv2d(out_channels, out_channels, kernel_size=(1, 3), padding=(0, 1), bias=False)
        self.bn_t_3 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.m_5 = nn.Conv2d(in_channels, out_channels, kernel_size=(5, 1), padding=(2, 0), bias=False)
        self.bn_m_5 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_5 = nn.Conv2d(out_channels, out_channels, kernel_size=(1, 5), padding=(0, 2), bias=False)
        self.bn_t_5 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.last = nn.Conv2d(out_channels, out_channels, kernel_size=(1, 1), padding=(0, 0), bias=False)
        self.bn_last = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x):
        x_3 = self.relu(self.bn_m_3(self.m_3(x)))
        x_3 = self.relu(self.bn_t_3(self.t_3(x_3)))
        x_5 = self.relu(self.bn_m_5(self.m_5(x)))
        x_5 = self.relu(self.bn_t_5(self.t_5(x_5)))
        x = x_3 + x_5
        return self.relu(self.bn_last(self.last(x)))


class Visual_Block(nn.Module):
    def __init__(self, in_channels, out_channels, is_down=False):
        super().__init__()
        self.relu = nn.ReLU()
        stride = (1, 2, 2) if is_down else (1, 1, 1)
        self.s_3 = nn.Conv3d(in_channels, out_channels, kernel_size=(1, 3, 3), stride=stride,
                             padding=(0, 1, 1), bias=False)
        self.bn_s_3 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_3 = nn.Conv3d(out_channels, out_channels, kernel_size=(3, 1, 1), padding=(1, 0, 0), bias=False)
        self.bn_t_3 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.s_5 = nn.Conv3d(in_channels, out_channels, kernel_size=(1, 5, 5), stride=stride,
                             padding=(0, 2, 2), bias=False)
        self.bn_s_5 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_5 = nn.Conv3d(out_channels, out_channels, kernel_size=(5, 1, 1), padding=(2, 0, 0), bias=False)
        self.bn_t_5 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.last = nn.Conv3d(out_channels, out_channels, kernel_size=(1, 1, 1), padding=(0, 0, 0), bias=False)
        self.bn_last = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x):
        x_3 = self.relu(self.bn_s_3(self.s_3(x)))
        x_3 = self.relu(self.bn_t_3(self.t_3(x_3)))
        x_5 = self.relu(self.bn_s_5(self.s_5(x)))
        x_5 = self.relu(self.bn_t_5(self.t_5(x_5)))
        x = x_3 + x_5
        return self.relu(self.bn_last(self.last(x)))


class visual_encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.block1 = Visual_Block(1, 32, is_down=True)
        self.pool1 = nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1))
        self.block2 = Visual_Block(32, 64)
        self.pool2 = nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1))
        self.block3 = Visual_Block(64, 128)
        self.maxpool = nn.AdaptiveMaxPool2d((1, 1))

    def forward(self, x):
        x = self.pool1(self.block1(x))
        x = self.pool2(self.block2(x))
        x = self.block3(x)
        x = x.transpose(1, 2)
        B, T, C, W, H = x.shape
        x = self.maxpool(x.reshape(B * T, C, W, H))
        return x.view(B, T, C)


class audio_encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.block1 = Audio_Block(1, 32)
        self.pool1 = nn.MaxPool3d(kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1))
        self.block2 = Audio_Block(32, 64)
        self.pool2 = nn.MaxPool3d(kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1))
        self.block3 = Audio_Block(64, 128)

    def forward(self, x):
        x = self.pool1(self.block1(x))
        x = self.pool2(self.block2(x))
        x = self.block3(x)
        x = torch.mean(x, dim=2, keepdim=True)
        return x.squeeze(2).transpose(1, 2)


class BGRU(nn.Module):
    def __init__(self, channel):
        super().__init__()
        self.gru_forward = nn.GRU(input_size=channel, hidden_size=channel, num_layers=1,
                                  bidirectional=False, bias=True, batch_first=True)
        self.gru_backward = nn.GRU(input_size=channel, hidden_size=channel, num_layers=1,
                                   bidirectional=False, bias=True, batch_first=True)
        self.gelu = nn.GELU()

    def forward(self, x):
        x, _ = self.gru_forward(x)
        x = self.gelu(x)
        x = torch.flip(x, dims=[1])
        x, _ = self.gru_backward(x)
        x = torch.flip(x, dims=[1])
        return self.gelu(x)


class ASD_Model(nn.Module):
    def __init__(self):
        super().__init__()
        self.visualEncoder = visual_encoder()
        self.audioEncoder = audio_encoder()
        self.GRU = BGRU(128)

    def forward_visual_frontend(self, x):
        B, T, W, H = x.shape
        x = x.view(B, 1, T, W, H)
        x = (x / 255 - 0.4161) / 0.1688
        return self.visualEncoder(x)

    def forward_audio_frontend(self, x):
        x = x.unsqueeze(1).transpose(2, 3)
        return self.audioEncoder(x)

    def forward_audio_visual_backend(self, x1, x2):
        x = self.GRU(x1 + x2)
        return torch.reshape(x, (-1, 128))


class _LossAVHead(nn.Module):
    """Inference half of upstream ``lossAV``: the 128 -> 2 classifier."""

    def __init__(self):
        super().__init__()
        self.FC = nn.Linear(128, 2)

    def forward(self, x):
        return self.FC(x.squeeze(1))[:, 1]


class LightASD(nn.Module):
    """Upstream ``ASD`` wrapper (inference only): ``model`` + ``lossAV`` head."""

    def __init__(self):
        super().__init__()
        self.model = ASD_Model()
        self.lossAV = _LossAVHead()

    @torch.no_grad()
    def score(self, audio_mfcc: torch.Tensor, faces: torch.Tensor) -> torch.Tensor:
        """Per-video-frame speaking logits.

        Args:
            audio_mfcc: [B, 4*T, 13] MFCC at 100 Hz.
            faces: [B, T, 112, 112] grayscale face crops at 25 fps (0..255).

        Returns:
            [B*T] logits; > 0 means speaking.
        """
        a = self.model.forward_audio_frontend(audio_mfcc)
        v = self.model.forward_visual_frontend(faces)
        return self.lossAV(self.model.forward_audio_visual_backend(a, v))


def load_light_asd(weights: Path, device: str = "cuda") -> LightASD:
    """Build the network and load the published weights (strict)."""
    net = LightASD()
    state = torch.load(str(weights), map_location="cpu", weights_only=True)
    state = {k.replace("module.", ""): v for k, v in state.items()
             if not k.startswith("lossV.")}
    missing, unexpected = net.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise RuntimeError(f"Light-ASD weights mismatch: missing={missing} "
                           f"unexpected={unexpected}")
    return net.to(device).eval()
