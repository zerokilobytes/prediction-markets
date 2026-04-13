# 1. Exit the old, slow environment
deactivate

# 2. Delete it entirely
rm -rf .venv

# 3. Create a NEW one using the specific 3.12 binary
python3.12 -m venv .venv

# 4. Activate it
source .venv/bin/activate

# 5. Verify the version now
python --version