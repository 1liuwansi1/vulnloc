"""Bounded wire-format normalization; never invent a tool or execute model code."""

import json
import re
import xml.etree.ElementTree as ET

WRAPPER = re.compile(r"</?(?:tool_call|tool_calls|tool_use)>\s*")
MAX_MESSAGE_BYTES = 1_000_000
TOOL_ARGUMENTS = {
    "list_dir": {"path"},
    "grep": {"pattern", "glob"},
    "read_file": {"path", "start_line", "end_line"},
}


def validate(obj):
    if not isinstance(obj, dict) or ("tool" in obj and "candidate_files" in obj):
        return None
    if "tool" in obj:
        name, args = obj.get("tool"), obj.get("args")
        if not isinstance(name, str) or name not in TOOL_ARGUMENTS:
            return None
        if set(obj) != {"tool", "args"} or not isinstance(args, dict):
            return None
        if set(args) - TOOL_ARGUMENTS[name]:
            return None
        if name == "grep" and (
            not isinstance(args.get("pattern"), str) or not args["pattern"]
        ):
            return None
        if name == "read_file" and (
            not isinstance(args.get("path"), str) or not args["path"]
        ):
            return None
        if any(not isinstance(args[k], str) for k in ("path", "glob") if k in args):
            return None
        if any(
            type(args[k]) is not int or args[k] < 1
            for k in ("start_line", "end_line")
            if k in args
        ):
            return None
        if (
            "start_line" in args
            and "end_line" in args
            and args["start_line"] > args["end_line"]
        ):
            return None
        return {"tool": name, "args": args}
    cs = obj.get("candidate_files")
    if not isinstance(cs, list) or len(cs) > 5:
        return None
    for candidate in cs:
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("path"), str)
            or not candidate["path"]
        ):
            return None
        if any(type(candidate.get(k)) is not int for k in ("line_start", "line_end")):
            return None
        if not 1 <= candidate["line_start"] <= candidate["line_end"]:
            return None
    return {"candidate_files": cs, "notes": obj.get("notes", "")}


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Ambiguous duplicate JSON key")
        obj[key] = value
    return obj


def decode(text):
    """Return (validated object, normalization label) or (None, rejected).

    Accept a single JSON payload with surrounding tool wrapper tags, including
    redundant or incomplete wrappers. Only surrounding tags may be removed;
    prose, multiple objects/tools, entities, and unnamed XML calls are rejected.
    One narrowly specified missing </tool> closing tag is repaired when the
    remaining payload is a single named tool containing complete parameters.
    """
    if not isinstance(text, str) or len(text.encode()) > MAX_MESSAGE_BYTES:
        return None, "rejected"
    value = text.strip()
    label = "json"
    if value.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", value, re.S)
        if not match:
            return None, "rejected"
        value, label = match[1].strip(), "fenced_json"
    while match := WRAPPER.match(value):
        value = value[match.end() :].strip()
        label = "wrapped_json"
    suffix = re.compile(r"\s*</(?:tool_call|tool_calls|tool_use)>\s*$")
    while match := suffix.search(value):
        value = value[: match.start()].strip()
        label = "wrapped_json"
    try:
        obj = json.loads(value, object_pairs_hook=unique_object)
        return validate(obj), label
    except (ValueError, TypeError):
        pass
    # Do not accept declarations, DTDs, entity references or arbitrary XML roots.
    if "<!" in value or "<?" in value or "&" in value:
        return None, "rejected"
    if re.fullmatch(
        r'<tool name="[a-z_]+">\s*(?:<parameter name="[a-z_]+">[^<>]*</parameter>\s*)+',
        value,
    ):
        value += "</tool>"
        label = "xml_missing_tool_close"
    else:
        label = "xml"
    try:
        node = ET.fromstring(value)
    except ET.ParseError:
        return None, "rejected"
    if node.tag not in ("tool", "invoke") or set(node.attrib) != {"name"}:
        return None, "rejected"
    if (node.text or "").strip() or (node.tail or "").strip():
        return None, "rejected"
    args = {}
    for child in node:
        if (
            child.tag != "parameter"
            or set(child.attrib) != {"name"}
            or len(child)
            or (child.tail or "").strip()
        ):
            return None, "rejected"
        key = child.attrib["name"]
        if key in args:
            return None, "rejected"
        scalar = child.text or ""
        if key in ("start_line", "end_line"):
            if not re.fullmatch(r"[1-9][0-9]*", scalar.strip()):
                return None, "rejected"
            scalar = int(scalar.strip())
        args[key] = scalar
    return validate({"tool": node.attrib["name"], "args": args}), label
