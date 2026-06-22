"""
llamacpp_manager.py — Gestion des serveurs llama.cpp locaux.

Architecture : un serveur llama-server.exe par modèle actif.
Chaque serveur écoute sur un port différent.
"""

from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ── Windows Job Object : tue les llama-server quand Python meurt (fermeture terminal) ──
_job_handle: int | None = None

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def _init_windows_job() -> int | None:
    """Crée un Job Object Windows — les enfants meurent quand Python se termine."""
    global _job_handle
    if sys.platform != "win32" or _job_handle:
        return _job_handle
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        logger.debug("CreateJobObjectW échoué")
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _kernel32.SetInformationJobObject(
        handle,
        _JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        _kernel32.CloseHandle(handle)
        logger.debug("SetInformationJobObject échoué")
        return None
    _job_handle = handle
    logger.debug("Job Object Windows actif (KILL_ON_JOB_CLOSE)")
    return handle


def _assign_process_to_job(process: subprocess.Popen) -> None:
    """Associe un llama-server au Job Object pour qu'il meure avec Python."""
    if sys.platform != "win32":
        return
    handle = _init_windows_job()
    if not handle:
        return
    proc_handle = getattr(process, "_handle", None)
    if not proc_handle:
        return
    if not _kernel32.AssignProcessToJobObject(handle, proc_handle):
        err = ctypes.get_last_error()
        # ERROR_ACCESS_DENIED (5) = process déjà dans un job — ignorer
        if err != 5:
            logger.debug("AssignProcessToJobObject échoué (code %s)", err)


def _taskkill_llama_servers() -> None:
    """Force l'arrêt de tous les llama-server.exe (y compris orphelins)."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "llama-server.exe"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=3,
        )
    except Exception as exc:
        logger.debug("taskkill llama-server: %s", exc)
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info.get("name") or "").lower() == "llama-server.exe":
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass


_orphan_cleanup_started = False


def _cleanup_orphans_async() -> None:
    """Nettoie les llama-server zombies sans bloquer le démarrage."""
    global _orphan_cleanup_started
    if _orphan_cleanup_started:
        return
    _orphan_cleanup_started = True

    def _run() -> None:
        _taskkill_llama_servers()
        logger.info("Nettoyage llama-server orphelins effectué")

    threading.Thread(target=_run, daemon=True, name="ARIA-LlamaCleanup").start()

LLAMA_SERVER_EXE = os.environ.get("LLAMA_SERVER_PATH", r"C:\llama.cpp\llama-server.exe")

OLLAMA_URL = "http://localhost:11434"

OLLAMA_BLOBS_DIR = Path(os.environ.get("USERPROFILE", "C:/Users/mathi")) / ".ollama/models/blobs"
OLLAMA_MANIFESTS_DIR = Path(os.environ.get("USERPROFILE", "C:/Users/mathi")) / ".ollama/models/manifests"
CUSTOM_MODELS_DIR: Path | None = None

DEFAULT_PARAMS = {
    "ctx_size": 4096,
    "n_gpu_layers": 99,  # tout sur GPU — RTX 5080 16GB VRAM
    "threads": 8,
    "batch_size": 512,
}

OLLAMA_GPU_LAYERS = 99
PREFER_OLLAMA_WHEN_NO_CUDA = True
BLOCK_CPU_WHEN_GPU = True
OLLAMA_AUTO_START = True

_OLLAMA_EXE: Path | None = None
_ollama_bootstrapped = False

_servers: dict[str, dict] = {}
_port_counter = 8080
_lock = threading.Lock()
_cuda_probe: bool | None = None
_llama_dir: Path | None = None
_cuda_bin_dirs: list[Path] = []
cuda_available: bool = False

_CUDA_ALT_NAMES: dict[str, list[str]] = {
    "cudart64_12.dll": ["cudart64_120.dll", "cudart64_110.dll"],
    "cublas64_12.dll": ["cublas64_120.dll", "cublas64_110.dll"],
    "cublasLt64_12.dll": ["cublasLt64_120.dll"],
}
_CUDA_REQUIRED_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll")


def _cuda_search_paths() -> list[Path]:
    paths: list[Path] = []
    if _llama_dir:
        paths.append(_llama_dir)
    paths.append(Path(r"C:/llama.cpp"))
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        paths.append(Path(cuda_path) / "bin")
    paths.extend([
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.9/bin"),
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.4/bin"),
        Path(r"C:/Windows/System32"),
    ])
    paths.extend(_cuda_bin_dirs)
    seen: set[str] = set()
    unique: list[Path] = []
    for p in paths:
        key = str(p).lower()
        if key not in seen and p:
            seen.add(key)
            unique.append(p)
    return unique


def _load_cuda_dlls() -> bool:
    """Charge manuellement les DLLs CUDA nécessaires pour llama.cpp."""
    loaded: list[str] = []
    for dll_name in _CUDA_REQUIRED_DLLS:
        dll_loaded = False
        names_to_try = [dll_name, *_CUDA_ALT_NAMES.get(dll_name, [])]
        for search_path in _cuda_search_paths():
            for name in names_to_try:
                dll_path = search_path / name
                if not dll_path.is_file():
                    continue
                try:
                    ctypes.CDLL(str(dll_path))
                    loaded.append(str(dll_path))
                    dll_loaded = True
                    logger.info("DLL CUDA chargée: %s", dll_path)
                    break
                except Exception as exc:
                    logger.debug("DLL %s échouée: %s", dll_path, exc)
            if dll_loaded:
                break
        if not dll_loaded:
            logger.warning("DLL introuvable: %s", dll_name)
    return len(loaded) > 0


def _check_cuda_available() -> bool:
    """Vérifie si CUDA est disponible pour llama.cpp."""
    if _load_cuda_dlls():
        return True
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            logger.info("GPU détecté: %s", result.stdout.strip())
            return nvidia_gpu_detected()
    except Exception:
        pass
    return False


def _copy_cuda_dlls_to_llama_dir() -> None:
    """Copie les DLLs CUDA dans le dossier llama-server si absentes."""
    llama_dir = _llama_dir or Path(r"C:/llama.cpp")
    if not llama_dir.is_dir():
        try:
            llama_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

    cuda_bin_dirs = [
        Path(os.environ.get("CUDA_PATH", "")) / "bin",
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.9/bin"),
        Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.4/bin"),
        *_venv_nvidia_cuda_dirs(),
    ]

    dlls_to_copy = [
        "cudart64_12.dll", "cudart64_120.dll",
        "cublas64_12.dll", "cublas64_120.dll",
        "cublasLt64_12.dll", "cublasLt64_120.dll",
        "nvblas64_12.dll",
    ]

    copied: list[str] = []
    for dll_name in dlls_to_copy:
        dest = llama_dir / dll_name
        if dest.is_file():
            continue
        for cuda_bin in cuda_bin_dirs:
            src = cuda_bin / dll_name
            if not src.is_file():
                continue
            try:
                shutil.copy2(src, dest)
                copied.append(dll_name)
                logger.info("DLL copiée: %s → %s", dll_name, llama_dir)
            except Exception as exc:
                logger.warning("Copie DLL %s échouée: %s", dll_name, exc)
            break

    if copied:
        logger.info("DLLs CUDA copiées dans %s: %s", llama_dir, copied)


def _resolve_server_exe(configured: str | None = None) -> str:
    """Cherche llama-server.exe (config, env, PATH, emplacements courants)."""
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    env_path = os.environ.get("LLAMA_SERVER_PATH")
    if env_path:
        candidates.append(Path(env_path))
    app_dir = Path(__file__).resolve().parent
    candidates.extend([
        app_dir / "llama-server.exe",
        app_dir / "bin" / "llama-server.exe",
        app_dir / "llama.cpp" / "llama-server.exe",
        app_dir / "tools" / "llama-server.exe",
        Path(r"C:\llama.cpp\llama-server.exe"),
        Path(r"C:\llama.cpp\build\bin\Release\llama-server.exe"),
        Path(r"C:\llama.cpp\build\bin\llama-server.exe"),
    ])
    which = shutil.which("llama-server") or shutil.which("llama-server.exe")
    if which:
        candidates.append(Path(which))
    for path in candidates:
        try:
            if path.is_file():
                return str(path.resolve())
        except OSError:
            continue
    return str(candidates[0]) if candidates else LLAMA_SERVER_EXE


def _venv_nvidia_cuda_dirs() -> list[Path]:
    """DLL CUDA du venv (pip nvidia-cuda-runtime-cu12 / nvidia-cublas-cu12)."""
    found: list[Path] = []
    for base in (
        Path(sys.prefix) / "Lib" / "site-packages" / "nvidia",
        Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages" / "nvidia",
    ):
        if not base.is_dir():
            continue
        for sub in base.iterdir():
            bin_dir = sub / "bin"
            if bin_dir.is_dir():
                found.append(bin_dir)
    return found


def nvidia_gpu_detected() -> bool:
    """True si nvidia-smi voit un GPU NVIDIA."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0 and "GPU" in out
    except Exception:
        return False


def _discover_cuda_bin_dirs(extra: str | None = None) -> list[Path]:
    """Répertoires contenant cudart/cublas (requis par ggml-cuda.dll)."""
    found: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        if path.is_dir():
            found.append(path)

    if extra:
        _add(Path(extra))
    cuda_home = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")
    if cuda_home:
        _add(Path(cuda_home) / "bin")

    toolkit = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    if toolkit.is_dir():
        for sub in sorted(toolkit.iterdir(), reverse=True):
            if sub.is_dir():
                _add(sub / "bin")

    if _llama_dir:
        _add(_llama_dir)

    for bin_dir in _venv_nvidia_cuda_dirs():
        _add(bin_dir)

    ollama_lib = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Ollama"
        / "lib"
        / "ollama"
    )
    if ollama_lib.is_dir():
        _add(ollama_lib)
        for sub in ollama_lib.iterdir():
            if sub.is_dir():
                _add(sub)
                cuda_bin = sub / "cuda_v12" / "bin"
                if cuda_bin.is_dir():
                    _add(cuda_bin)

    for part in os.environ.get("PATH", "").split(os.pathsep):
        if part and ("cuda" in part.lower() or "nvidia" in part.lower()):
            _add(Path(part))

    return found


def _cuda_runtime_on_path() -> bool:
    """True si les DLL CUDA runtime sont trouvables."""
    names = (
        "cudart64_13.dll",
        "cudart64_12.dll",
        "cudart64_11.dll",
        "cublas64_12.dll",
        "cublasLt64_12.dll",
    )
    for directory in _cuda_bin_dirs:
        if any((directory / name).is_file() for name in names):
            return True
    for name in names:
        if shutil.which(name):
            return True
    return False


def probe_llamacpp_cuda(force: bool = False) -> bool:
    """
    Vérifie si llama.cpp peut utiliser le GPU (ggml-cuda + runtime CUDA).
    Sans cudart/cublas, llama-server charge tout en RAM système.
    """
    global _cuda_probe, cuda_available
    if _cuda_probe is not None and not force:
        return _cuda_probe

    llama_dir = Path(LLAMA_SERVER_EXE).parent if Path(LLAMA_SERVER_EXE).exists() else None
    has_cuda_dll = bool(llama_dir and (llama_dir / "ggml-cuda.dll").is_file())
    if not has_cuda_dll:
        logger.warning("ggml-cuda.dll absent — llama.cpp sera CPU-only")
        _cuda_probe = False
        cuda_available = False
        return False

    _load_cuda_dlls()
    if not _cuda_runtime_on_path():
        logger.warning(
            "Runtime CUDA introuvable (cudart/cublas) — llama.cpp reste CPU-only. "
            "Lance scripts/fix_cuda_dlls.ps1 ou installe CUDA 12.x."
        )
        _cuda_probe = False
        cuda_available = False
        return False

    _cuda_probe = True
    cuda_available = True
    logger.info("CUDA détecté pour llama.cpp — offload GPU activé")
    return True


def should_use_ollama_gpu() -> bool:
    """True si Ollama GPU doit être préféré à llama-server CPU."""
    if not PREFER_OLLAMA_WHEN_NO_CUDA:
        return False
    if probe_llamacpp_cuda():
        return False
    if not nvidia_gpu_detected():
        return False
    if is_ollama_available():
        return True
    if OLLAMA_AUTO_START and ensure_ollama_running():
        return True
    return False


def should_block_cpu_llama() -> bool:
    """Bloque llama-server CPU-only quand un GPU NVIDIA est présent."""
    return BLOCK_CPU_WHEN_GPU and nvidia_gpu_detected() and not probe_llamacpp_cuda()


def _resolve_ollama_exe() -> Path | None:
    if _OLLAMA_EXE and _OLLAMA_EXE.is_file():
        return _OLLAMA_EXE
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(r"C:\Program Files\Ollama\ollama.exe"),
    ):
        if candidate.is_file():
            return candidate
    which = shutil.which("ollama") or shutil.which("ollama.exe")
    return Path(which) if which else None


def ensure_ollama_running(timeout: float = 25.0) -> bool:
    """Démarre `ollama serve` si besoin (inférence VRAM)."""
    global _ollama_bootstrapped
    if is_ollama_available():
        _ollama_bootstrapped = True
        return True
    if _ollama_bootstrapped:
        return False
    exe = _resolve_ollama_exe()
    if not exe:
        logger.warning("ollama.exe introuvable — impossible d'utiliser la VRAM")
        return False
    env = os.environ.copy()
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    env.setdefault("OLLAMA_GPU", "1")
    try:
        subprocess.Popen(
            [str(exe), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            env=env,
        )
        logger.info("Démarrage Ollama serve (GPU)…")
    except Exception as exc:
        logger.error("Impossible de lancer Ollama: %s", exc)
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_ollama_available():
            _ollama_bootstrapped = True
            logger.info("Ollama prêt — modèles sur VRAM")
            return True
        time.sleep(0.5)
    return False


def warmup_ollama_model(model_name: str) -> bool:
    """Précharge un modèle dans la VRAM via Ollama."""
    if not ensure_ollama_running():
        return False
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model_name,
                "prompt": " ",
                "stream": False,
                "keep_alive": "30m",
                "options": ollama_gpu_options(),
            },
            timeout=120,
        )
        logger.info("Warmup Ollama GPU: %s", model_name)
        return True
    except Exception as exc:
        logger.debug("Warmup Ollama %s échoué: %s", model_name, exc)
        return False


def get_gpu_status() -> dict:
    """État GPU pour logs / UI."""
    cuda_ok = probe_llamacpp_cuda()
    gpu = nvidia_gpu_detected()
    return {
        "nvidia_gpu": gpu,
        "cuda_runtime": cuda_ok,
        "llama_cpp_gpu": cuda_ok,
        "ollama_running": is_ollama_available(),
        "inference_backend": (
            "llama.cpp-gpu"
            if cuda_ok
            else ("ollama-gpu" if gpu and is_ollama_available() else "cpu")
        ),
    }


def ollama_gpu_options() -> dict:
    """Options Ollama pour forcer l'offload VRAM."""
    return {"num_gpu": OLLAMA_GPU_LAYERS}


def _build_server_env() -> dict[str, str]:
    env = os.environ.copy()
    if _cuda_bin_dirs:
        extra = os.pathsep.join(str(p) for p in _cuda_bin_dirs)
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
        env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    return env


def configure(cfg: dict | None = None) -> None:
    """Applique la section llamacpp de config.yaml."""
    global LLAMA_SERVER_EXE, OLLAMA_BLOBS_DIR, OLLAMA_MANIFESTS_DIR
    global CUSTOM_MODELS_DIR, DEFAULT_PARAMS, _port_counter
    global OLLAMA_GPU_LAYERS, PREFER_OLLAMA_WHEN_NO_CUDA
    global BLOCK_CPU_WHEN_GPU, OLLAMA_AUTO_START, _OLLAMA_EXE
    global _llama_dir, _cuda_bin_dirs, _cuda_probe

    if not cfg:
        return

    ollama_path = cfg.get("ollama_path")
    if ollama_path:
        try:
            _OLLAMA_EXE = Path(str(ollama_path))
        except Exception:
            _OLLAMA_EXE = None

    llamacpp = cfg.get("llamacpp") or {}
    configured_path = llamacpp.get("server_path") if llamacpp.get("server_path") else None
    LLAMA_SERVER_EXE = _resolve_server_exe(str(configured_path) if configured_path else None)
    _llama_dir = Path(LLAMA_SERVER_EXE).parent if Path(LLAMA_SERVER_EXE).exists() else None
    if Path(LLAMA_SERVER_EXE).exists():
        logger.info("llama-server: %s", LLAMA_SERVER_EXE)
    else:
        logger.warning(
            "llama-server introuvable (%s) — modèles locaux indisponibles, IA cloud OK",
            LLAMA_SERVER_EXE,
        )
    _cuda_bin_dirs = _discover_cuda_bin_dirs(str(llamacpp.get("cuda_path") or "") or None)
    _cuda_probe = None
    _init_windows_job()
    _cleanup_orphans_async()
    _copy_cuda_dlls_to_llama_dir()
    global cuda_available
    cuda_available = _check_cuda_available()
    if llamacpp.get("ollama_gpu_layers") is not None:
        OLLAMA_GPU_LAYERS = int(llamacpp["ollama_gpu_layers"])
    if "prefer_ollama_when_no_cuda" in llamacpp:
        PREFER_OLLAMA_WHEN_NO_CUDA = bool(llamacpp["prefer_ollama_when_no_cuda"])
    if "force_gpu" in llamacpp:
        BLOCK_CPU_WHEN_GPU = bool(llamacpp["force_gpu"])
    elif "block_cpu_when_gpu" in llamacpp:
        BLOCK_CPU_WHEN_GPU = bool(llamacpp["block_cpu_when_gpu"])
    if "ollama_auto_start" in llamacpp:
        OLLAMA_AUTO_START = bool(llamacpp["ollama_auto_start"])
    probe_llamacpp_cuda(force=True)
    status = get_gpu_status()
    logger.info(
        "GPU: %s | CUDA runtime: %s | backend inférence: %s",
        "RTX détecté" if status["nvidia_gpu"] else "aucun",
        "OK" if status["cuda_runtime"] else "manquant",
        status["inference_backend"],
    )
    if llamacpp.get("blobs_dir"):
        OLLAMA_BLOBS_DIR = Path(str(llamacpp["blobs_dir"]))
    if llamacpp.get("manifests_dir"):
        OLLAMA_MANIFESTS_DIR = Path(str(llamacpp["manifests_dir"]))
    if llamacpp.get("models_dir"):
        CUSTOM_MODELS_DIR = Path(str(llamacpp["models_dir"]))

    for key in ("ctx_size", "n_gpu_layers", "threads", "batch_size"):
        if key in llamacpp:
            DEFAULT_PARAMS[key] = llamacpp[key]
    if llamacpp.get("base_port") is not None:
        _port_counter = int(llamacpp["base_port"])


def _blob_from_manifest(manifest_path: Path) -> Path | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for layer in manifest.get("layers", []):
            if layer.get("mediaType") == "application/vnd.ollama.image.model":
                digest = layer["digest"].replace("sha256:", "sha256-")
                blob_path = OLLAMA_BLOBS_DIR / digest
                if blob_path.exists():
                    return blob_path
    except Exception as exc:
        logger.debug("Erreur lecture manifeste %s: %s", manifest_path, exc)
    return None


def _find_in_custom_dir(model_name: str) -> Path | None:
    if not CUSTOM_MODELS_DIR or not CUSTOM_MODELS_DIR.exists():
        return None

    base = model_name.split(":", 1)[0].lower()
    needles = {
        base,
        base.replace(".", ""),
        model_name.lower(),
        model_name.replace(":", "-").lower(),
    }

    for path in CUSTOM_MODELS_DIR.rglob("*"):
        if not path.is_file():
            continue
        name_lower = path.name.lower()
        if path.suffix.lower() == ".gguf":
            if any(n in name_lower for n in needles if n):
                return path
        elif not path.suffix and path.stat().st_size > 50_000_000:
            if any(n in name_lower for n in needles if n):
                return path
    return None


def _find_model_blob(model_name: str) -> Path | None:
    """
    Trouve le fichier GGUF d'un modèle depuis les blobs Ollama ou models_dir.
    model_name: ex 'llama3.2:1b', 'qwen3:14b'
    """
    parts = model_name.split(":", 1)
    base = parts[0]
    tag = parts[1] if len(parts) > 1 else "latest"

    manifests_base = OLLAMA_MANIFESTS_DIR / "registry.ollama.ai" / "library"
    candidates = [
        manifests_base / base / tag,
        manifests_base / base / "latest",
    ]

    for manifest_path in candidates:
        if manifest_path.is_file():
            blob = _blob_from_manifest(manifest_path)
            if blob:
                logger.info(
                    "Modèle '%s' → %s (%.1f Go)",
                    model_name,
                    blob.name,
                    blob.stat().st_size / 1e9,
                )
                return blob

    custom = _find_in_custom_dir(model_name)
    if custom:
        logger.info("Modèle '%s' → custom %s", model_name, custom)
        return custom

    logger.warning("Modèle '%s' non trouvé dans les blobs Ollama", model_name)
    return None


def list_available_models() -> list[str]:
    """Liste tous les modèles disponibles (manifestes Ollama + models_dir)."""
    models: list[str] = []
    seen: set[str] = set()
    manifests_base = OLLAMA_MANIFESTS_DIR / "registry.ollama.ai" / "library"

    if manifests_base.exists():
        for model_dir in manifests_base.iterdir():
            if not model_dir.is_dir():
                continue
            for tag_file in model_dir.iterdir():
                if not tag_file.is_file():
                    continue
                model_name = f"{model_dir.name}:{tag_file.name}"
                if _blob_from_manifest(tag_file):
                    if model_name not in seen:
                        seen.add(model_name)
                        models.append(model_name)

    if CUSTOM_MODELS_DIR and CUSTOM_MODELS_DIR.exists():
        for path in CUSTOM_MODELS_DIR.rglob("*.gguf"):
            name = path.stem.replace("-", ":").replace("_", ":")
            if name not in seen:
                seen.add(name)
                models.append(name)

    return sorted(models)


def model_exists(model_name: str) -> bool:
    return _find_model_blob(model_name) is not None


def _next_port() -> int:
    global _port_counter
    with _lock:
        port = _port_counter
        _port_counter += 1
        return port


def _build_server_command(
    model_path: Path | str,
    port: int,
    n_gpu_layers: int,
    ctx_size: int,
    threads: int,
    batch_size: int,
) -> list[str]:
    cmd = [
        LLAMA_SERVER_EXE,
        "--model",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(ctx_size),
        "--n-gpu-layers",
        str(n_gpu_layers),
        "--threads",
        str(threads),
        "--batch-size",
        str(batch_size),
        "--no-mmap",
        "--log-disable",
    ]
    if probe_llamacpp_cuda():
        cmd.extend(["--flash-attn", "on"])
    return cmd


def start_model_server(model_name: str, params: dict | None = None) -> dict | None:
    """
    Démarre un serveur llama-server.exe pour un modèle donné.
    Retourne {process, port, url, model_path, model_name} ou None si échec.
    """
    if should_use_ollama_gpu():
        logger.info(
            "Inférence Ollama GPU — serveur llama.cpp non démarré (modèle=%s)",
            model_name,
        )
        warmup_ollama_model(model_name)
        return None

    if should_block_cpu_llama():
        logger.error(
            "Refus llama-server CPU-only pour '%s' — GPU présent sans CUDA. "
            "Installe nvidia-cuda-runtime-cu12 ou lance Ollama.",
            model_name,
        )
        ensure_ollama_running()
        return None

    if model_name in _servers:
        info = _servers[model_name]
        if info["process"].poll() is None:
            logger.info("Serveur '%s' déjà actif sur port %d", model_name, info["port"])
            return info
        logger.warning("Serveur '%s' mort — redémarrage", model_name)
        del _servers[model_name]

    model_path = _find_model_blob(model_name)
    if not model_path:
        logger.error("Impossible de trouver le modèle '%s'", model_name)
        return None

    if not Path(LLAMA_SERVER_EXE).exists():
        logger.warning(
            "llama-server.exe non trouvé: %s — https://github.com/ggerganov/llama.cpp/releases",
            LLAMA_SERVER_EXE,
        )
        return None

    port = _next_port()
    p = {**DEFAULT_PARAMS, **(params or {})}

    cmd = _build_server_command(
        model_path,
        port,
        int(p.get("n_gpu_layers", DEFAULT_PARAMS["n_gpu_layers"])),
        int(p.get("ctx_size", DEFAULT_PARAMS["ctx_size"])),
        int(p.get("threads", DEFAULT_PARAMS["threads"])),
        int(p.get("batch_size", DEFAULT_PARAMS["batch_size"])),
    )

    log_dir = Path(os.environ.get("TEMP", ".")) / "aria_llama_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = log_dir / f"llama_{model_name.replace(':', '_')}_{port}.log"

    logger.info(
        "Démarrage llama-server: modèle=%s, port=%d, n_gpu_layers=%d, cuda=%s",
        model_name,
        port,
        p.get("n_gpu_layers", DEFAULT_PARAMS["n_gpu_layers"]),
        probe_llamacpp_cuda(),
    )
    logger.debug("Commande: %s", " ".join(cmd))

    try:
        stderr_file = open(stderr_log, "w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            cwd=str(_llama_dir) if _llama_dir else None,
            env=_build_server_env(),
            creationflags=CREATE_NO_WINDOW,
        )
        _assign_process_to_job(process)

        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            time.sleep(0.5)
            if process.poll() is not None:
                stderr_file.close()
                tail = ""
                try:
                    tail = stderr_log.read_text(encoding="utf-8", errors="replace")[-1500:]
                except OSError:
                    pass
                logger.error(
                    "llama-server a planté immédiatement (modèle=%s). Log: %s\n%s",
                    model_name,
                    stderr_log,
                    tail,
                )
                return None
            try:
                resp = requests.get(f"{url}/health", timeout=1)
                if resp.status_code == 200:
                    logger.info("Serveur '%s' prêt sur port %d", model_name, port)
                    break
            except Exception:
                pass
        else:
            stderr_file.close()
            logger.error("Timeout démarrage serveur '%s' (voir %s)", model_name, stderr_log)
            process.kill()
            return None

        stderr_file.close()
        try:
            log_text = stderr_log.read_text(encoding="utf-8", errors="replace")
            if "CUDA" in log_text.upper() and "CPU" in log_text:
                logger.info("Backend GPU llama.cpp actif pour '%s'", model_name)
            elif "host memory" in log_text.lower() and "device_info" in log_text.lower():
                if "CUDA" not in log_text and "Vulkan" not in log_text:
                    logger.warning(
                        "llama-server '%s' semble CPU-only (RAM) — voir %s",
                        model_name,
                        stderr_log,
                    )
        except OSError:
            pass

        info = {
            "process": process,
            "port": port,
            "url": url,
            "model_path": str(model_path),
            "model_name": model_name,
        }
        _servers[model_name] = info
        return info

    except Exception as exc:
        logger.error("Erreur démarrage serveur '%s': %s", model_name, exc)
        return None


def get_server_url(model_name: str) -> str | None:
    """Retourne l'URL d'un serveur actif, None si pas démarré."""
    info = _servers.get(model_name)
    if info and info["process"].poll() is None:
        return info["url"]
    return None


def is_ollama_available() -> bool:
    """True si l'API Ollama répond sur localhost:11434."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def get_fallback_url(model_name: str) -> str | None:
    """Retourne l'URL Ollama si disponible, None sinon."""
    if is_ollama_available():
        return OLLAMA_URL
    return None


def is_running(model_name: str | None = None) -> bool:
    """True si au moins un serveur (ou le modèle donné) est actif."""
    if model_name:
        return get_server_url(model_name) is not None
    return any(info["process"].poll() is None for info in _servers.values())


def stop_all_servers() -> None:
    """Arrête tous les serveurs llama.cpp et nettoie les processus orphelins."""
    for model_name, info in list(_servers.items()):
        proc = info.get("process")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        logger.info("Serveur '%s' arrêté", model_name)
    _servers.clear()
    _taskkill_llama_servers()


def stop_server(model_name: str) -> None:
    """Arrête un serveur spécifique."""
    info = _servers.pop(model_name, None)
    if info:
        try:
            info["process"].terminate()
        except Exception:
            pass
        logger.info("Serveur '%s' arrêté", model_name)


def stop_servers_except(keep_models: set[str | None]) -> None:
    """Arrête tous les serveurs sauf ceux dont le nom est dans keep_models."""
    keep = {m for m in keep_models if m}
    for model_name in list(_servers.keys()):
        if model_name not in keep and not any(k in model_name for k in keep):
            stop_server(model_name)


atexit.register(stop_all_servers)
