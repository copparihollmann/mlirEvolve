# mlirEvolve

Store your API key inside of a txt file named `API_KEY.txt`.
This will automatically be ignored for git.

Then call:

```bash
export OPENAI_API_KEY=$(<API_KEY.txt)
```

So that we can use it for OpenEvolve.

## TIPS

Useful command for tree:

```bash
 tree -L 3 --gitignore -I 'third_party'
```

We can use:

```bash
pip install -e .
```

To install everything locally.

