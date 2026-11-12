"""Network bridge that lets a ChatGPT agent delegate tasks to Claude Code (requirement R1).

The Claude side runs a small authenticated HTTP server that hands each prompt to Claude Code;
the ChatGPT side submits prompts and retrieves structured results over HTTP.
"""
