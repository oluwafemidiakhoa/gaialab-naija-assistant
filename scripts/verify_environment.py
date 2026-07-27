from __future__ import annotations

import platform
import sys


def main() -> int:
    try:
        import torch
        import transformers
        import peft
        import accelerate
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except Exception as exc:
        print(f"ENVIRONMENT CHECK FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("Environment OK")
    print(f"Python:       {sys.version.split()[0]}")
    print(f"Platform:     {platform.platform()}")
    print(f"torch:        {torch.__version__}")
    print(f"transformers: {transformers.__version__}")
    print(f"peft:         {peft.__version__}")
    print(f"accelerate:   {accelerate.__version__}")
    print(f"CUDA:         {torch.cuda.is_available()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
