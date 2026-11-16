import json, secrets

MOM_DEEPSEEK_KEY = "MOM_DEEPSEEK_KEY"      # <- paste Mom's DeepSeek key
ME_DEEPSEEK_KEY  = "ME_DEEPSEEK_KEY"       # <- paste your DeepSeek key
SHARED_GEMINI    = "SHARED_GEMINI_KEY"     # <- paste the Gemini key
SHARED_PEXELS    = "SHARED_PEXELS_KEY"     # <- paste the Pexels key

bundles = {
    "rk-" + secrets.token_hex(16): {"label": "Mom", "provider": "deepseek",
        "keys": {"deepseek": MOM_DEEPSEEK_KEY, "gemini": SHARED_GEMINI, "pexels": SHARED_PEXELS}},
    "rk-" + secrets.token_hex(16): {"label": "Me", "provider": "deepseek",
        "keys": {"deepseek": ME_DEEPSEEK_KEY, "gemini": SHARED_GEMINI, "pexels": SHARED_PEXELS}},
}

print(json.dumps(bundles))          # <- paste this whole line into REXTBOOKS_KEY_BUNDLES
print()
for code, bundle in bundles.items():
    print(f"{bundle['label']}: {code}")   # <- send Mom the first one