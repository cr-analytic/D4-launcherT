"""Minimal ctypes binding to libnvidia-ml, with an nvidia-smi fallback.

Deliberately not pynvml: this keeps the tool dependency-free and lets us poll at
250 ms without paying ~80 ms of process spawn per sample.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from dataclasses import dataclass

NVML_SUCCESS = 0
NVML_ERROR_NOT_SUPPORTED = 3
NVML_TEMPERATURE_GPU = 0

# Field-value API. Instant power is what matters here: connector damage tracks
# transient current, and the averaged reading smooths those peaks away.
NVML_FI_DEV_POWER_AVERAGE = 186
NVML_FI_DEV_POWER_INSTANT = 187
NVML_POWER_SCOPE_GPU = 0

NVML_VALUE_TYPE_DOUBLE = 0
NVML_VALUE_TYPE_UNSIGNED_INT = 1
NVML_VALUE_TYPE_UNSIGNED_LONG = 2
NVML_VALUE_TYPE_UNSIGNED_LONG_LONG = 3
NVML_VALUE_TYPE_SIGNED_LONG_LONG = 4
NVML_VALUE_TYPE_SIGNED_INT = 5


class NvmlError(RuntimeError):
    pass


class _Value(ctypes.Union):
    _fields_ = [
        ("dVal", ctypes.c_double),
        ("uiVal", ctypes.c_uint),
        ("ulVal", ctypes.c_ulong),
        ("ullVal", ctypes.c_ulonglong),
        ("sllVal", ctypes.c_longlong),
        ("siVal", ctypes.c_int),
    ]


class _FieldValue(ctypes.Structure):
    _fields_ = [
        ("fieldId", ctypes.c_uint),
        ("scopeId", ctypes.c_uint),
        ("timestamp", ctypes.c_longlong),
        ("latencyUsec", ctypes.c_longlong),
        ("valueType", ctypes.c_int),
        ("nvmlReturn", ctypes.c_int),
        ("value", _Value),
    ]


def _field_number(fv: _FieldValue) -> float:
    v = fv.value
    return {
        NVML_VALUE_TYPE_DOUBLE: lambda: v.dVal,
        NVML_VALUE_TYPE_UNSIGNED_INT: lambda: float(v.uiVal),
        NVML_VALUE_TYPE_UNSIGNED_LONG: lambda: float(v.ulVal),
        NVML_VALUE_TYPE_UNSIGNED_LONG_LONG: lambda: float(v.ullVal),
        NVML_VALUE_TYPE_SIGNED_LONG_LONG: lambda: float(v.sllVal),
        NVML_VALUE_TYPE_SIGNED_INT: lambda: float(v.siVal),
    }[fv.valueType]()


@dataclass
class Sample:
    """One poll of the GPU. Power figures are whole-board, in watts."""

    watts: float
    instant: bool  # True if from the instantaneous sensor, False if averaged
    temp_c: float | None = None
    limit_w: float | None = None


@dataclass
class DeviceInfo:
    name: str
    driver: str
    index: int
    limit_w: float | None
    backend: str


class PowerSource:
    """Common interface: describe() once, read() in a loop, close() at exit."""

    def describe(self) -> DeviceInfo:
        raise NotImplementedError

    def read(self) -> Sample:
        raise NotImplementedError

    def close(self) -> None:
        pass


class NvmlSource(PowerSource):
    def __init__(self, index: int = 0):
        self.index = index
        self._lib = self._load()
        self._check(self._lib.nvmlInit_v2())
        self._initialised = True

        count = ctypes.c_uint()
        self._check(self._lib.nvmlDeviceGetCount_v2(ctypes.byref(count)))
        if count.value == 0:
            raise NvmlError("NVML reports no GPUs")
        if index >= count.value:
            raise NvmlError(f"GPU index {index} out of range ({count.value} present)")

        self._handle = ctypes.c_void_p()
        self._check(
            self._lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(self._handle))
        )
        # Probed once: if the instant sensor is missing we stop asking for it.
        self._has_instant = self._probe_instant()

    @staticmethod
    def _load() -> ctypes.CDLL:
        for name in ("libnvidia-ml.so.1", "libnvidia-ml.so"):
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
        raise NvmlError(
            "libnvidia-ml.so.1 not found — is the proprietary NVIDIA driver loaded?"
        )

    def _check(self, rc: int) -> None:
        if rc != NVML_SUCCESS:
            self._lib.nvmlErrorString.restype = ctypes.c_char_p
            msg = self._lib.nvmlErrorString(rc) or b"unknown"
            raise NvmlError(f"NVML error {rc}: {msg.decode(errors='replace')}")

    def _probe_instant(self) -> bool:
        try:
            return self._field_watts(NVML_FI_DEV_POWER_INSTANT) is not None
        except NvmlError:
            return False

    def _field_watts(self, field_id: int) -> float | None:
        fv = _FieldValue()
        fv.fieldId = field_id
        fv.scopeId = NVML_POWER_SCOPE_GPU
        rc = self._lib.nvmlDeviceGetFieldValues(self._handle, 1, ctypes.byref(fv))
        if rc != NVML_SUCCESS or fv.nvmlReturn != NVML_SUCCESS:
            return None
        try:
            return _field_number(fv) / 1000.0  # milliwatts -> watts
        except KeyError:
            return None

    def describe(self) -> DeviceInfo:
        buf = ctypes.create_string_buffer(96)
        self._check(self._lib.nvmlDeviceGetName(self._handle, buf, 96))

        drv = ctypes.create_string_buffer(80)
        if self._lib.nvmlSystemGetDriverVersion(drv, 80) != NVML_SUCCESS:
            drv.value = b"unknown"

        return DeviceInfo(
            name=buf.value.decode(errors="replace"),
            driver=drv.value.decode(errors="replace"),
            index=self.index,
            limit_w=self._limit_w(),
            backend="NVML" + (" (instant)" if self._has_instant else " (averaged)"),
        )

    def _limit_w(self) -> float | None:
        mw = ctypes.c_uint()
        for fn in ("nvmlDeviceGetEnforcedPowerLimit", "nvmlDeviceGetPowerManagementLimit"):
            if getattr(self._lib, fn)(self._handle, ctypes.byref(mw)) == NVML_SUCCESS:
                return mw.value / 1000.0
        return None

    def read(self) -> Sample:
        watts = None
        instant = False
        if self._has_instant:
            watts = self._field_watts(NVML_FI_DEV_POWER_INSTANT)
            instant = watts is not None
        if watts is None:
            mw = ctypes.c_uint()
            self._check(self._lib.nvmlDeviceGetPowerUsage(self._handle, ctypes.byref(mw)))
            watts = mw.value / 1000.0

        temp = ctypes.c_uint()
        temp_c = None
        if (
            self._lib.nvmlDeviceGetTemperature(
                self._handle, NVML_TEMPERATURE_GPU, ctypes.byref(temp)
            )
            == NVML_SUCCESS
        ):
            temp_c = float(temp.value)

        return Sample(watts=watts, instant=instant, temp_c=temp_c, limit_w=self._limit_w())

    def close(self) -> None:
        if getattr(self, "_initialised", False):
            self._lib.nvmlShutdown()
            self._initialised = False


class SmiSource(PowerSource):
    """Fallback for when libnvidia-ml can't be dlopen'd but the CLI works."""

    QUERY = "power.draw,temperature.gpu,power.limit"

    def __init__(self, index: int = 0):
        self.index = index
        self.exe = shutil.which("nvidia-smi")
        if not self.exe:
            raise NvmlError("nvidia-smi not on PATH")
        self.read()  # fail fast rather than at the first UI tick

    def _query(self, fields: str) -> list[str]:
        out = subprocess.run(
            [
                self.exe,
                f"--id={self.index}",
                f"--query-gpu={fields}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            raise NvmlError(f"nvidia-smi failed: {out.stderr.strip() or out.returncode}")
        return [f.strip() for f in out.stdout.strip().splitlines()[0].split(",")]

    @staticmethod
    def _num(raw: str) -> float | None:
        try:
            return float(raw)
        except ValueError:
            return None  # "[N/A]" and friends

    def describe(self) -> DeviceInfo:
        name, driver = self._query("name,driver_version")
        limit = self._num(self._query("power.limit")[0])
        return DeviceInfo(
            name=name, driver=driver, index=self.index, limit_w=limit, backend="nvidia-smi"
        )

    def read(self) -> Sample:
        power, temp, limit = self._query(self.QUERY)
        watts = self._num(power)
        if watts is None:
            raise NvmlError("nvidia-smi reports no power reading for this GPU")
        return Sample(
            watts=watts, instant=False, temp_c=self._num(temp), limit_w=self._num(limit)
        )


def open_source(index: int = 0) -> PowerSource:
    """NVML first, nvidia-smi second, and report both failures if neither works."""
    try:
        return NvmlSource(index)
    except (NvmlError, OSError) as nvml_err:
        try:
            return SmiSource(index)
        except (NvmlError, OSError, subprocess.SubprocessError) as smi_err:
            raise NvmlError(f"NVML: {nvml_err}\nnvidia-smi: {smi_err}") from nvml_err
