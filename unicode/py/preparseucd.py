#!/usr/bin/python2.6
# -*- coding: utf-8 -*-
# Copyright (c) 2009-2011 International Business Machines
# Corporation and others. All Rights Reserved.
#
#   file name:  preparseucd.py
#   encoding:   US-ASCII
#   tab size:   8 (not used)
#   indentation:4
#
#   created on: 2011nov03 (forked from ucdcopy.py)
#   created by: Markus W. Scherer
#
# Copies Unicode Character Database (UCD) files from a tree
# of files downloaded from (for example) ftp://www.unicode.org/Public/6.1.0/
# to ICU's source/data/unidata/ and source/test/testdata/
# and modifies some of the files to make them more compact.
# Parses them and writes unidata/ppucd.txt (PreParsed UCD) with simple syntax.
#
# Invoke with three command-line parameters:
# 1. source folder with UCD files
# 2. ICU source root folder
# 3. ICU tools root folder
#
# Sample invocation:
#   ~/svn.icu/tools/trunk/src/unicode$ py/preparseucd.py ~/uni61/20111205mod/ucd ~/svn.icu/trunk/src ~/svn.icu/tools/trunk/src

import array
import bisect
import codecs
import os
import os.path
import re
import shutil
import sys

# Unicode version ---------------------------------------------------------- ***

_ucd_version = "?"
_copyright = ""
_terms_of_use = ""

# ISO 15924 script codes --------------------------------------------------- ***

# Script codes from ISO 15924 http://www.unicode.org/iso15924/codechanges.html
# that are not yet in the UCD.
_scripts_only_in_iso15924 = (
    "Blis", "Cirt", "Cyrs",
    "Egyd", "Egyh", "Geok",
    "Hans", "Hant", "Hmng", "Hung",
    "Inds", "Jpan", "Latf", "Latg", "Lina",
    "Maya", "Moon", "Perm", "Roro",
    "Sara", "Sgnw", "Syre", "Syrj", "Syrn",
    "Teng", "Visp", "Zxxx",

    "Kore", "Mani", "Phlp", "Phlv", "Zmth", "Zsym",

    "Nkgb",

    "Bass", "Dupl", "Elba", "Gran",
    "Kpel", "Loma", "Mend", "Narb", "Nbat",
    "Palm", "Sind", "Wara",

    "Afak", "Jurc", "Mroo", "Nshu", "Tang", "Wole",

    "Khoj", "Tirh"
)

# Properties --------------------------------------------------------------- ***

_ignored_properties = set((
  # Other_Xyz only contribute to Xyz, store only the latter.
  "OAlpha",
  "ODI",
  "OGr_Ext",
  "OIDC",
  "OIDS",
  "OLower",
  "OMath",
  "OUpper",
  # Further properties that just contribute to others.
  "JSN",
  # These properties just don't seem useful.
  "XO_NFC",
  "XO_NFD",
  "XO_NFKC",
  "XO_NFKD",
  # ICU does not use Unihan properties.
  "cjkAccountingNumeric",
  "cjkOtherNumeric",
  "cjkPrimaryNumeric",
  "cjkCompatibilityVariant",
  "cjkIICore",
  "cjkIRG_GSource",
  "cjkIRG_HSource",
  "cjkIRG_JSource",
  "cjkIRG_KPSource",
  "cjkIRG_KSource",
  "cjkIRG_MSource",
  "cjkIRG_TSource",
  "cjkIRG_USource",
  "cjkIRG_VSource",
  "cjkRSUnicode"
))

# Dictionary of properties.
# Keyed by normalized property names and aliases.
# Each value is a tuple with
# 0: Type of property (binary, enum, ...)
# 1: List of aliases; short & long name followed by other aliases.
#    The short name is "" if it is listed as "n/a" in PropertyValueAliases.txt.
# 2: Dictionary, maps short property value names
#    initially to None, later to ICU4C API enum constants.
# 3: Dictionary of property values.
#    For Catalog & Enumerated properties,
#    maps each value name to a list of aliases.
#    Empty for other types of properties.
_properties = {}

# Dictionary of binary-property values which we store as False/True.
# Same as the values dictionary of one of the binary properties.
_binary_values = {}

# Dictionary of null values.
# Keyed by short property names.
# These are type-specific values for properties that occur in the data.
# They are overridden by _defaults, block and code point properties.
_null_values = {}

# Property value names for null values.
# We do not store these in _defaults.
_null_names = frozenset(("<none>", "NaN"))

# Dictionary of explicit default property values.
# Keyed by short property names.
_defaults = {}

# _null_values overridden by explicit _defaults.
# Initialized after parsing is done.
_null_or_defaults = {}

# Dictionary of short property names mapped to ICU4C UProperty enum constants.
_property_name_to_enum = {}

# Dictionary of short gc value names mapped to UCharCategory enum constants.
_gc_vname_to_enum = {}

_non_alnum_re = re.compile("[^a-zA-Z0-9]")

def NormPropName(pname):
  """Returns a normalized form of pname.
  Removes non-ASCII-alphanumeric characters and lowercases letters."""
  return _non_alnum_re.sub("", pname).lower()


def GetProperty(pname):
  """Returns the _properties value for the pname.
  Returns null if the property is ignored.
  Caches alternate spellings of the property name."""
  # Try the input name.
  prop = _properties.get(pname)
  if prop != None: return prop
  if pname in _ignored_properties: return None
  # Try the normalized input name.
  norm_name = NormPropName(pname)
  prop = _properties.get(norm_name)
  if prop != None:
    _properties[pname] = prop  # Cache prop under this new name spelling.
    return prop
  elif pname in _ignored_properties:
    _ignored_properties.add(pname)  # Remember to ignore this new name spelling.
    return None
  else:
    raise NameError("unknown property %s\n" % pname)


def GetShortPropertyName(pname):
  if pname in _null_values: return pname  # pname is already the short name.
  prop = GetProperty(pname)
  return prop[1][0] if prop else ""  # "" for ignored properties.


def GetShortPropertyValueName(prop, vname):
  if vname in prop[2]: return vname
  values = prop[3]
  aliases = values.get(vname)
  if aliases == None:
    norm_name = NormPropName(vname)
    aliases = values.get(norm_name)
    if aliases == None:
      raise NameError("unknown value name %s for property %s\n" %
                      (vname, prop[1][0]))
    values[vname] = aliases
  short_name = aliases[0]
  return short_name if short_name else aliases[1]  # Long name if no short name.


def NormalizePropertyValue(prop, vname):
  if prop[2]:  # Binary/Catalog/Enumerated property.
    value = GetShortPropertyValueName(prop, vname)
    if prop[0] == "Binary":
      value = value == "Y"
    if prop[1][0].endswith("ccc"):
      value = int(value)
  else:
    value = vname
  return value

# Character data ----------------------------------------------------------- ***

# Lists of NamesList h1 and h2 headings.
# Each h1 value is a (start, end, comment) tuple.
# Each h2 value is a (cp, comment) tuple.
_h1 = []
_h2 = []

# List of Unicode blocks.
# Each item is a tuple of start & end code point integers
# and a dictionary of default property values.
_blocks = []

# List of ranges with algorithmic names.
# Each value is a list of [start, end, type, prefix]
# where prefix is optional.
_alg_names_ranges = []

# List of Unicode character ranges and their properties,
# stored as an inversion map with range_start & props dictionary.
# Starts with one range for all of Unicode without any properties.
# Setting values subdivides ranges.
_starts = array.array('l', [0, 0x110000])  # array of int32_t
_props = [{}]  # props for 0 but not 110000

def FindRange(x):
  """ Binary search for x in the inversion map.
  Returns the smallest i where x < _starts[i]"""
  return bisect.bisect(_starts, x) - 1


def UpdateProps(start, end, update):
  assert 0 <= start <= end <= 0x10ffff
  (need_to_update, do_update, u) = (update[0], update[1], update[2])
  # Find the index i of the range in _starts that contains start.
  i = FindRange(start)
  limit = end + 1
  # Intersect [start, limit[ with ranges in _starts.
  c_start = _starts[i]
  c_limit = _starts[i + 1]
  c_props = _props[i]
  # c_start <= start < c_limit
  if c_start < start:
    update_limit = c_limit if c_limit <= limit else limit
    if need_to_update(u, start, update_limit - 1, c_props):
      # Split off [c_start, start[ with a copy of c_props.
      i += 1
      c_props = c_props.copy()
      _starts.insert(i, start)
      _props.insert(i, c_props)
      c_start = start
  # Modify all ranges that are fully inside [start, limit[.
  while c_limit <= limit:
    # start <= c_start < c_limit <= limit
    if need_to_update(u, c_start, c_limit - 1, c_props):
      do_update(u, c_start, c_limit - 1, c_props)
    if c_limit == 0x110000: return
    i += 1
    c_start = c_limit
    c_limit = _starts[i + 1]
    c_props = _props[i]
  if c_start < limit and need_to_update(u, c_start, limit - 1, c_props):
    # Split off [limit, c_limit[ with a copy of c_props.
    _starts.insert(i + 1, limit)
    _props.insert(i + 1, c_props.copy())
    # Modify [c_start, limit[ c_props.
    do_update(u, c_start, limit - 1, c_props)


def NeedToSetProps(props, start, end, c_props):
  """Returns True if props is not a sub-dict of c_props."""
  for (pname, value) in props.iteritems():
    if pname not in c_props or value != c_props[pname]: return True
  return False


def DoSetProps(props, start, end, c_props):
  c_props.update(props)


def SetProps(start, end, props):
  UpdateProps(start, end, (NeedToSetProps, DoSetProps, props))


def NeedToSetAlways(nv, start, end, c_props):
  return True


# For restoring boundaries after merging adjacent same-props ranges.
def AddBoundary(x):
  """Ensure that there is a range start/limit at x."""
  assert 0 <= x <= 0x10ffff
  i = FindRange(x)
  if _starts[i] == x: return
  # Split the range at x.
  c_start = _starts[i]
  c_limit = _starts[i + 1]
  c_props = _props[i]
  # c_start < x < c_limit
  i += 1
  _starts.insert(i, x)
  _props.insert(i, c_props.copy())


def SetDefaultValue(pname, value):
  """Sets the property's default value. Ignores null values."""
  prop = GetProperty(pname)
  if prop and value not in _null_names:
    value = NormalizePropertyValue(prop, value)
    if value != _null_values[prop[1][0]]:
      _defaults[prop[1][0]] = value
      SetProps(0, 0x10ffff, {prop[1][0]: value})


def SetBinaryPropertyToTrue(pname, start, end):
  prop = GetProperty(pname)
  if prop:
    assert prop[0] == "Binary"
    SetProps(start, end, {prop[1][0]: True})


def SetPropValue(prop, vname, start, end):
  value = NormalizePropertyValue(prop, vname)
  SetProps(start, end, {prop[1][0]: value})


def SetPropertyValue(pname, vname, start, end):
  prop = GetProperty(pname)
  if prop: SetPropValue(prop, vname, start, end)

# Parsing ------------------------------------------------------------------ ***

_stripped_cp_re = re.compile("([0-9a-fA-F]+)$")
_stripped_range_re = re.compile("([0-9a-fA-F]+)\.\.([0-9a-fA-F]+)$")
_missing_re = re.compile("# *@missing: *0000\.\.10FFFF *; *(.+)$")

def ReadUCDLines(in_file, want_ranges=True, want_other=False,
                 want_comments=False, want_missing=False):
  """Parses lines from a semicolon-delimited UCD text file.
  Strips comments, ignores empty and all-comment lines.
  Returns a tuple (type, line, ...).
  """
  for line in in_file:
    line = line.strip()
    if not line: continue
    if line.startswith("#"):  # whole-line comment
      if want_missing:
        match = _missing_re.match(line)
        if match:
          fields = match.group(1).split(";")
          for i in xrange(len(fields)): fields[i] = fields[i].strip()
          yield ("missing", line, fields)
          continue
      if want_comments: yield ("comment", line)
      continue
    comment_start = line.find("#")  # inline comment
    if comment_start >= 0:
      line = line[:comment_start].rstrip()
      if not line: continue
    fields = line.split(";")
    for i in xrange(len(fields)): fields[i] = fields[i].strip()
    if want_ranges:
      first = fields[0]
      match = _stripped_range_re.match(first)
      if match:
        start = int(match.group(1), 16)
        end = int(match.group(2), 16)
        yield ("range", line, start, end, fields)
        continue
      match = _stripped_cp_re.match(first)
      if match:
        c = int(match.group(1), 16)
        yield ("range", line, c, c, fields)
        continue
    if want_other:
      yield ("other", line, fields)
    else:
      raise SyntaxError("unable to parse line\n  %s\n" % line)


def AddBinaryProperty(short_name, long_name):
  _null_values[short_name] = False
  bin_prop = _properties["Math"]
  prop = ("Binary", [short_name, long_name], bin_prop[2], bin_prop[3])
  _properties[short_name] = prop
  _properties[long_name] = prop
  _properties[NormPropName(short_name)] = prop
  _properties[NormPropName(long_name)] = prop


def AddPOSIXBinaryProperty(short_name, long_name):
  AddBinaryProperty(short_name, long_name)
  # This is to match UProperty UCHAR_POSIX_ALNUM etc.
  _properties["posix" + NormPropName(short_name)] = _properties[short_name]


# Match a comment line like
# PropertyAliases-6.1.0.txt
# and extract the Unicode version.
_ucd_version_re = re.compile("# *PropertyAliases" +
                             "-([0-9]+(?:\\.[0-9]+)*)(?:d[0-9]+)?" +
                             "\\.txt")

def ParsePropertyAliases(in_file):
  global _copyright, _terms_of_use, _ucd_version
  prop_type_nulls = {
    "Binary": False,
    "Catalog": "??",  # Must be specified, e.g., in @missing line.
    "Enumerated": "??",  # Must be specified.
    "Numeric": "NaN",
    "String": "",
    "Miscellaneous": ""
  }
  for data in ReadUCDLines(in_file, want_ranges=False,
                           want_other=True, want_comments=True):
    if data[0] == "comment":
      line = data[1]
      match = _ucd_version_re.match(line)
      if match:
        _ucd_version = match.group(1)
      elif line.startswith("# Copyright"):
        _copyright = line
      elif "terms of use" in line:
        _terms_of_use = line
      else:
        words = line[1:].lstrip().split()
        if len(words) == 2 and words[1] == "Properties":
          prop_type = words[0]
          null_value = prop_type_nulls[prop_type]
    else:
      # type == "other"
      aliases = data[2]
      name = aliases[0]
      if name in _ignored_properties:
        for alias in aliases:
          _ignored_properties.add(alias)
          _ignored_properties.add(NormPropName(alias))
      else:
        if name.endswith("ccc"):
          _null_values[name] = 0
        else:
          _null_values[name] = null_value
        prop = (prop_type, aliases, {}, {})
        for alias in aliases:
          _properties[alias] = prop
          _properties[NormPropName(alias)] = prop
  # Add provisional and ICU-specific properties we need.
  # We add some in support of runtime API, even if we do not write
  # data for them to ppucd.txt (e.g., lccc & tccc).
  # We add others just to represent UCD data that contributes to
  # some functionality, although Unicode has not "blessed" them
  # as separate properties (e.g., Turkic_Case_Folding).

  # Turkic_Case_Folding: The 'T' mappings in CaseFolding.txt.
  name = "Turkic_Case_Folding"
  _null_values[name] = ""
  prop = ("String", [name, name], {}, {})
  _properties[name] = prop
  _properties[NormPropName(name)] = prop
  # Conditional_Case_Mappings: SpecialCasing.txt lines with conditions.
  name = "Conditional_Case_Mappings"
  _null_values[name] = ""
  prop = ("Miscellaneous", [name, name], {}, {})
  _properties[name] = prop
  _properties[NormPropName(name)] = prop
  # lccc = ccc of first cp in canonical decomposition.
  _null_values["lccc"] = 0
  ccc_prop = list(_properties["ccc"])
  ccc_prop[1] = ["lccc", "Lead_Canonical_Combining_Class"]
  prop = tuple(ccc_prop)
  _properties["lccc"] = prop
  _properties["Lead_Canonical_Combining_Class"] = prop
  _properties["leadcanonicalcombiningclass"] = prop
  # tccc = ccc of last cp in canonical decomposition.
  _null_values["tccc"] = 0
  ccc_prop[1] = ["tccc", "Trail_Canonical_Combining_Class"]
  prop = tuple(ccc_prop)
  _properties["tccc"] = prop
  _properties["Trail_Canonical_Combining_Class"] = prop
  _properties["trailcanonicalcombiningclass"] = prop
  # Script_Extensions
  if "scx" not in _properties:
    _null_values["scx"] = ""
    prop = ("Miscellaneous", ["scx", "Script_Extensions"], {}, {})
    _properties["scx"] = prop
    _properties["Script_Extensions"] = prop
    _properties["scriptextensions"] = prop
  # General Category as a bit mask.
  _null_values["gcm"] = "??"
  gc_prop = _properties["gc"]
  prop = ("Bitmask", ["gcm", "General_Category_Mask"], gc_prop[2], gc_prop[3])
  _properties["gcm"] = prop
  _properties["General_Category_Mask"] = prop
  _properties["generalcategorymask"] = prop
  # Various binary properties.
  AddBinaryProperty("Sensitive", "Case_Sensitive")
  AddBinaryProperty("nfdinert", "NFD_Inert")
  AddBinaryProperty("nfkdinert", "NFKD_Inert")
  AddBinaryProperty("nfcinert", "NFC_Inert")
  AddBinaryProperty("nfkcinert", "NFKC_Inert")
  AddBinaryProperty("segstart", "Segment_Starter")
  # C/POSIX character classes that do not have Unicode property [value] aliases.
  # See uchar.h.
  AddPOSIXBinaryProperty("alnum", "alnum")
  AddPOSIXBinaryProperty("blank", "blank")
  AddPOSIXBinaryProperty("graph", "graph")
  AddPOSIXBinaryProperty("print", "print")
  AddPOSIXBinaryProperty("xdigit", "xdigit")


def ParsePropertyValueAliases(in_file):
  global _binary_values
  for data in ReadUCDLines(in_file, want_ranges=False,
                           want_other=True, want_missing=True):
    if data[0] == "missing":
      SetDefaultValue(data[2][0], data[2][1])
    else:
      # type == "other"
      fields = data[2]
      pname = fields[0]
      prop = GetProperty(pname)
      if prop:
        del fields[0]  # Only the list of aliases remains.
        short_name = fields[0]
        if short_name == "n/a":  # no short name
          fields[0] = ""
          short_name = fields[1]
        prop[2][short_name] = None
        values = prop[3]
        for alias in fields:
          if alias:
            values[alias] = fields
            values[NormPropName(alias)] = fields
        if prop[0] == "Binary" and not _binary_values:
          _binary_values = values
  # Some of the @missing lines with non-null default property values
  # are in files that we do not parse;
  # either because the data for that property is easily
  # (i.e., the @missing line would be the only reason to parse such a file)
  # or because we compute the property at runtime,
  # such as the Hangul_Syllable_Type.
  if "dt" not in _defaults:  # DerivedDecompositionType.txt
    _defaults["dt"] = "None"
  if "nt" not in _defaults:  # DerivedNumericType.txt
    _defaults["nt"] = "None"
  if "hst" not in _defaults:  # HangulSyllableType.txt
    _defaults["hst"] = "NA"
  if "gc" not in _defaults:  # No @missing line in any .txt file?
    _defaults["gc"] = "Cn"
  # Copy the gc default value to gcm.
  _defaults["gcm"] = _defaults["gc"]
  # Add ISO 15924-only script codes.
  # Only for the ICU script code API, not necessary for parsing the UCD.
  script_prop = _properties["sc"]
  short_script_names = script_prop[2]  # dict
  script_values = script_prop[3]  # dict
  remove_scripts = []
  for script in _scripts_only_in_iso15924:
    if script in short_script_names:
      remove_scripts.append(script)
    else:
      short_script_names[script] = None
      # Do not invent a Unicode long script name before the UCD adds the script.
      script_list = [script, script]  # [short, long]
      script_values[script] = script_list
      # Probably not necessary because
      # we will not parse these scripts from the UCD:
      script_values[NormPropName(script)] = script_list
  if remove_scripts:
    raise ValueError(
        "remove %s from _scripts_only_in_iso15924" % remove_scripts)


def ParseBlocks(in_file):
  for data in ReadUCDLines(in_file, want_missing=True):
    if data[0] == "missing":
      SetDefaultValue("blk", data[2][0])
    else:
      # type == "range"
      (start, end, name) = (data[2], data[3], data[4][1])
      _blocks.append((start, end, {"blk": name}))
      SetPropertyValue("blk", name, start, end)
  _blocks.sort()
  # Check for overlapping blocks.
  prev_end = -1
  for b in _blocks:
    start = b[0]
    end = b[1]
    if prev_end >= start:
      raise ValueError(
          "block %04lX..%04lX %s overlaps with another " +
          "ending at %04lX\n  %s\n" %
          (start, end, b[2]["blk"], prev_end))
    prev_end = end


def ParseUnicodeData(in_file):
  dt_prop = GetProperty("dt")
  range_first_line = ""
  range_first = -1
  for data in ReadUCDLines(in_file, want_missing=True):
    # type == "range"
    (line, c, end, fields) = (data[1], data[2], data[3], data[4])
    assert c == end
    name = fields[1]
    if name.startswith("<"):
      if name.endswith(", First>"):
        if range_first >= 0:
          raise SyntaxError(
              "error: unterminated range started at\n  %s\n" %
              range_first_line)
        range_first = c
        range_first_line = line
        continue
      elif name.endswith(", Last>"):
        if range_first < 0:
          raise SyntaxError(
              "error: range end without start at\n  %s\n" %
              line)
        elif range_first > c:
          raise SyntaxError(
              "error: range start/end out of order at\n  %s\n  %s\n" %
              (range_first_line, line))
        first_name = range_first_line.split(";")[1][1:-8]
        name = name[1:-7]
        if first_name != name:
          raise SyntaxError(
              "error: range start/end name mismatch at\n  %s\n  %s\n" %
              (range_first_line, line))
        end = c
        c = range_first
        range_first = -1
        # Remember algorithmic name ranges.
        if "Ideograph" in name:
          _alg_names_ranges.append([c, end, "han", "CJK UNIFIED IDEOGRAPH-"])
        elif name == "Hangul Syllable":
          _alg_names_ranges.append([c, end, "hangul"])
        name = ""
      else:
        # Ignore non-names like <control>.
        name = ""
    props = {}
    if name: props["na"] = name
    props["gc"] = fields[2]
    ccc = int(fields[3])
    if ccc: props["ccc"] = ccc
    props["bc"] = fields[4]
    # Decomposition type & mapping.
    dm = fields[5]
    if dm:
      if dm.startswith("<"):
        dt_limit = dm.index(">")
        dt = NormalizePropertyValue(dt_prop, dm[1:dt_limit])
        dm = dm[dt_limit + 1:].lstrip()
      else:
        dt = "Can"
      props["dt"] = dt
      props["dm"] = dm
    # Numeric type & value.
    decimal = fields[6]
    digit = fields[7]
    nv = fields[8]
    if (decimal and decimal != nv) or (digit and digit != nv):
      raise SyntaxError("error: numeric values differ at\n  %s\n" % line)
    if nv:
      props["nv"] = nv
      props["nt"] = "De" if decimal else "Di" if digit else "Nu"
    if fields[9] == "Y": props["Bidi_M"] = True
    # ICU 49 and above does not support Unicode_1_Name any more.
    # See ticket #9013.
    # na1 = fields[10]
    # if na1: props["na1"] = na1
    # ISO_Comment is deprecated and has no values.
    # isc = fields[11]
    # if isc: props["isc"] = isc
    # Simple case mappings.
    suc = fields[12]
    slc = fields[13]
    stc = fields[14]
    if suc: props["suc"] = suc
    if slc: props["slc"] = slc
    if stc: props["stc"] = stc
    SetProps(c, end, props)
  if range_first >= 0:
    raise SyntaxError(
        "error: unterminated range started at\n  %s\n" %
        range_first_line)
  # Hangul syllables have canonical decompositions which are not listed in UnicodeData.txt.
  SetPropertyValue("dt", "Can", 0xac00, 0xd7a3)
  _alg_names_ranges.sort()


_names_h1_re = re.compile("@@\t([0-9a-fA-F]+)\t(.+?)\t([0-9a-fA-F]+)$")
_names_h2_re = re.compile("@\t\t(.+)")
_names_char_re = re.compile("([0-9a-fA-F]+)\t.+")

def ParseNamesList(in_file):
  pending_h2 = ""
  for line in in_file:
    line = line.strip()
    if not line: continue
    match = _names_h1_re.match(line)
    if match:
      pending_h2 = ""  # Drop a pending h2 when we get to an h1.
      start = int(match.group(1), 16)
      end = int(match.group(3), 16)
      comment = match.group(2).replace(u"\xa0", " ")
      _h1.append((start, end, comment))
      continue
    match = _names_h2_re.match(line)
    if match:
      pending_h2 = match.group(1).replace(u"\xa0", " ")
      continue
    if pending_h2:
      match = _names_char_re.match(line)
      if match:
        c = int(match.group(1), 16)
        _h2.append((c, pending_h2))
        pending_h2 = ""
  _h1.sort()
  _h2.sort()


def ParseNamedProperties(in_file):
  """Parses a .txt file where the first column is a code point range
  and the second column is a property name.
  Sets binary properties to True,
  and other properties to the values in the third column."""
  for data in ReadUCDLines(in_file, want_missing=True):
    if data[0] == "missing":
      SetDefaultValue(data[2][0], data[2][1])
    else:
      # type == "range"
      if len(data[4]) == 2:
        SetBinaryPropertyToTrue(data[4][1], data[2], data[3])
      else:
        SetPropertyValue(data[4][1], data[4][2], data[2], data[3])


def ParseOneProperty(in_file, pname):
  """Parses a .txt file where the first column is a code point range
  and the second column is the value of a known property."""
  prop = GetProperty(pname)
  for data in ReadUCDLines(in_file, want_missing=True):
    if data[0] == "missing":
      SetDefaultValue(pname, data[2][0])
    else:
      # type == "range"
      SetPropValue(prop, data[4][1], data[2], data[3])


def ParseBidiMirroring(in_file): ParseOneProperty(in_file, "bmg")
def ParseDerivedAge(in_file): ParseOneProperty(in_file, "age")
def ParseDerivedBidiClass(in_file): ParseOneProperty(in_file, "bc")
def ParseDerivedJoiningGroup(in_file): ParseOneProperty(in_file, "jg")
def ParseDerivedJoiningType(in_file): ParseOneProperty(in_file, "jt")
def ParseEastAsianWidth(in_file): ParseOneProperty(in_file, "ea")
def ParseGraphemeBreakProperty(in_file): ParseOneProperty(in_file, "GCB")
def ParseIndicMatraCategory(in_file): ParseOneProperty(in_file, "InMC")
def ParseIndicSyllabicCategory(in_file): ParseOneProperty(in_file, "InSC")
def ParseLineBreak(in_file): ParseOneProperty(in_file, "lb")
def ParseScripts(in_file): ParseOneProperty(in_file, "sc")
def ParseScriptExtensions(in_file): ParseOneProperty(in_file, "scx")
def ParseSentenceBreak(in_file): ParseOneProperty(in_file, "SB")
def ParseWordBreak(in_file): ParseOneProperty(in_file, "WB")


def DoSetNameAlias(alias, start, end, c_props):
  if "Name_Alias" in c_props:
    c_props["Name_Alias"] += ',' + alias
  else:
    c_props["Name_Alias"] = alias


def ParseNameAliases(in_file):
  """Parses Name_Alias from NameAliases.txt.
  A character can have multiple aliases.

  In Unicode 6.0, there are two columns,
  with a name correction in the second column.

  In Unicode 6.1, there are three columns.
  The second contains an alias, the third its type.
  The documented types are:
    correction, control, alternate, figment, abbreviation

  This function does not sort the types, assuming they appear in this order."""
  for data in ReadUCDLines(in_file):
    start = data[2]
    end = data[3]
    if start != end:
      raise ValueError("NameAliases.txt has an alias for a range %04lX..%04lX" %
                       (start, end))
    fields = data[4]
    if len(fields) == 2:
      alias = "correction=" + fields[1]
    else:
      alias = fields[2] + '=' + fields[1]
    update = (NeedToSetAlways, DoSetNameAlias, alias)
    UpdateProps(start, end, update)


def NeedToSetNumericValue(nv, start, end, c_props):
  c_nv = c_props.get("nv")
  if c_nv == None:
    # DerivedNumericValues.txt adds a Numeric_Value.
    assert "nt" not in c_props
    return True
  if nv != c_nv:
    raise ValueError("UnicodeData.txt has nv=%s for %04lX..%04lX " +
                     "but DerivedNumericValues.txt has nv=%s" %
                     (c_nv, start, end, nv))
  return False


def DoSetNumericValue(nv, start, end, c_props):
  c_props.update({"nt": "Nu", "nv": nv})


def ParseDerivedNumericValues(in_file):
  """Parses DerivedNumericValues.txt.
  For most characters, the numeric type & value were parsed previously
  from UnicodeData.txt but that does not show the values for Han characters.
  Here we check that values match those from UnicodeData.txt
  and add new ones."""
  # Ignore the @missing line which has an incorrect number of fields,
  # and the "NaN" in the wrong field (at least in Unicode 5.1..6.1).
  # Also, "NaN" is just the Numeric null value anyway.
  for data in ReadUCDLines(in_file):
    # Conditional update to the numeric value in the 4th field.
    update = (NeedToSetNumericValue, DoSetNumericValue, data[4][3])
    UpdateProps(data[2], data[3], update)


def ParseCaseFolding(in_file):
  for data in ReadUCDLines(in_file, want_missing=True):
    if data[0] == "missing":
      assert data[2][0] == "C"  # common to scf & cf
      SetDefaultValue("scf", data[2][1])
      SetDefaultValue("cf", data[2][1])
    else:
      # type == "range"
      start = data[2]
      end = data[3]
      status = data[4][1]
      mapping = data[4][2]
      assert status in "CSFT"
      if status == "C":
        SetProps(start, end, {"scf": mapping, "cf": mapping})
      elif status == "S":
        SetPropertyValue("scf", mapping, start, end)
      elif status == "F":
        SetPropertyValue("cf", mapping, start, end)
      else:  # status == "T"
        SetPropertyValue("Turkic_Case_Folding", mapping, start, end)


def DoSetConditionalCaseMappings(ccm, start, end, c_props):
  if "Conditional_Case_Mappings" in c_props:
    c_props["Conditional_Case_Mappings"] += ',' + ccm
  else:
    c_props["Conditional_Case_Mappings"] = ccm


def ParseSpecialCasing(in_file):
  for data in ReadUCDLines(in_file, want_missing=True):
    if data[0] == "missing":
      SetDefaultValue("lc", data[2][0])
      SetDefaultValue("tc", data[2][1])
      SetDefaultValue("uc", data[2][2])
    else:
      # type == "range"
      start = data[2]
      end = data[3]
      fields = data[4]
      if len(fields) < 5 or not fields[4]:
        # Unconditional mappings.
        SetProps(start, end, {"lc": fields[1], "tc": fields[2], "uc": fields[3]})
      else:
        # Conditional_Case_Mappings
        ccm = (fields[4] + ":lc=" + fields[1] +
               "&tc=" + fields[2] + "&uc=" + fields[3])
        update = (NeedToSetAlways, DoSetConditionalCaseMappings, ccm)
        UpdateProps(start, end, update)

# Postprocessing ----------------------------------------------------------- ***

def CompactBlock(b, i):
  assert b[0] == _starts[i]
  orig_i = i
  # Count the number of occurrences of each property's value in this block.
  num_cp_so_far = 0
  prop_counters = {}
  while True:
    start = _starts[i]
    if start > b[1]: break
    num_cp_in_this_range = _starts[i + 1] - start
    props = _props[i]
    for (pname, value) in props.iteritems():
      if pname in prop_counters:
        counter = prop_counters[pname]
      else:
        counter = {_null_or_defaults[pname]: num_cp_so_far}
        prop_counters[pname] = counter
      if value in counter:
        counter[value] += num_cp_in_this_range
      else:
        counter[value] = num_cp_in_this_range
    # Also count default values for properties that do not occur in a range.
    for pname in prop_counters:
      if pname not in props:
        counter = prop_counters[pname]
        value = _null_or_defaults[pname]
        counter[value] += num_cp_in_this_range
    num_cp_so_far += num_cp_in_this_range
    # Invariant: For each counter, the sum of counts must equal num_cp_so_far.
    i += 1
  # For each property that occurs within this block,
  # set the most common value as a block property value.
  b_props = b[2]
  for (pname, counter) in prop_counters.iteritems():
    max_value = None
    max_count = 0
    num_unique = 0
    for (value, count) in counter.iteritems():
      if count > max_count:
        max_value = value
        max_count = count
      if count == 1: num_unique += 1
    if max_value != _null_or_defaults[pname]:
      # Avoid picking randomly among several unique values.
      if (max_count > 1 or num_unique == 1):
        b_props[pname] = max_value
  # For each range and property, remove the default+block value
  # but set the default value if that property was not set
  # (i.e., it used to inherit the default value).
  b_defaults = _null_or_defaults.copy()
  b_defaults.update(b_props)
  i = orig_i
  while True:
    start = _starts[i]
    if start > b[1]: break
    props = _props[i]
    for pname in prop_counters:
      if pname in props:
        if props[pname] == b_defaults[pname]: del props[pname]
      elif pname in b_props:
        # b_props only has non-default values.
        # Set the default value if it used to be inherited.
        props[pname] = _null_or_defaults[pname]
    i += 1
  # Return the _starts index of the first range after this block.
  return i


def CompactNonBlock(limit, i):
  """Remove default property values from between-block ranges."""
  while True:
    start = _starts[i]
    if start >= limit: break
    props = _props[i]
    for pname in props.keys():  # .keys() is a copy so we can del props[pname].
      if props[pname] == _null_or_defaults[pname]: del props[pname]
    i += 1
  # Return the _starts index of the first range after this block.
  return i


def CompactBlocks():
  """Optimizes block properties.
  Sets properties on blocks to the most commonly used values,
  and removes default+block values from code point properties."""
  # Ensure that there is a boundary in _starts for each block
  # so that the simple mixing method below works.
  for b in _blocks: AddBoundary(b[0])
  # Walk through ranges and blocks together.
  i = 0
  for b in _blocks:
    b_start = b[0]
    if _starts[i] < b_start:
      i = CompactNonBlock(b_start, i)
    i = CompactBlock(b, i)
  CompactNonBlock(0x110000, i)

# Output ------------------------------------------------------------------- ***

def AppendRange(fields, start, end):
  if start == end:
    fields.append("%04lX" % start)
  else:
    fields.append("%04lX..%04lX" % (start, end))


def AppendProps(fields, props):
  # Sort property names (props keys) by their normalized forms
  # and output properties in that order.
  for pname in sorted(props, key=NormPropName):
    value = props[pname]
    if isinstance(value, bool):
      if not value: pname = "-" + pname
      fields.append(pname)
    else:
      fields.append("%s=%s" % (pname, value))


def WriteFieldsRangeProps(fields, start, end, props, out_file):
  AppendRange(fields, start, end)
  AppendProps(fields, props)
  out_file.write(";".join(fields))
  out_file.write("\n")


def WritePreparsedUCD(out_file):
  out_file.write("# Preparsed UCD generated by ICU preparseucd.py\n");
  if _copyright: out_file.write(_copyright + "\n")
  if _terms_of_use: out_file.write(_terms_of_use + "\n")
  out_file.write("ucd;%s\n\n" % _ucd_version)
  # Sort property names (props keys) by their normalized forms
  # and output properties in that order.
  pnames = sorted(_null_values, key=NormPropName)
  for pname in pnames:
    prop = _properties[pname]
    out_file.write(";".join(["property", prop[0]] + prop[1]))
    out_file.write("\n")
  out_file.write("\n")
  out_file.write(";".join(["binary"] + _binary_values["N"]))
  out_file.write("\n")
  out_file.write(";".join(["binary"] + _binary_values["Y"]))
  out_file.write("\n")
  for pname in pnames:
    prop = _properties[pname]
    short_names = prop[2]
    if short_names and prop[0] != "Binary":
      for name in sorted(short_names):
        out_file.write(";".join(["value", prop[1][0]] + prop[3][name]))
        out_file.write("\n")
  out_file.write("\n")
  # Ensure that there is a boundary in _starts for each
  # range of data we mix into the output,
  # so that the simple mixing method below works.
  for b in _blocks: AddBoundary(b[0])
  for r in _alg_names_ranges: AddBoundary(r[0])
  for h in _h1: AddBoundary(h[0])
  for h in _h2: AddBoundary(h[0])
  # Write the preparsed data.
  # TODO: doc syntax
  # - ppucd.txt = preparsed UCD
  # - Only whole-line comments starting with #, no inline comments.
  # - defaults must precede any block or cp lines
  # - block;a..b must precede any cp lines with code points in a..b
  # - Some code may require that all cp lines with code points in a..b
  #   appear between block;a..b and the next block line.
  # - block lines are not required; cp lines can have data for
  #   ranges outside of blocks.
  WriteFieldsRangeProps(["defaults"], 0, 0x10ffff, _defaults, out_file)
  i_blocks = 0
  i_alg = 0
  i_h1 = 0
  i_h2 = 0
  for i in xrange(len(_starts) - 1):
    start = _starts[i]
    end = _starts[i + 1] - 1
    # Block with default properties.
    if i_blocks < len(_blocks) and start == _blocks[i_blocks][0]:
      b = _blocks[i_blocks]
      WriteFieldsRangeProps(["\nblock"], b[0], b[1], b[2], out_file)
      i_blocks += 1
    # NamesList h1 heading (for [most of] a block).
    if i_h1 < len(_h1) and start == _h1[i_h1][0]:
      h = _h1[i_h1]
      out_file.write("# %04lX..%04lX %s\n" % (h[0], h[1], h[2]))
      i_h1 += 1
    # Algorithmic-names range.
    if i_alg < len(_alg_names_ranges) and start == _alg_names_ranges[i_alg][0]:
      r = _alg_names_ranges[i_alg]
      fields = ["algnamesrange"]
      AppendRange(fields, r[0], r[1])
      fields.extend(r[2:])
      out_file.write(";".join(fields))
      out_file.write("\n")
      i_alg += 1
    # NamesList h2 heading.
    if i_h2 < len(_h2) and start == _h2[i_h2][0]:
      out_file.write("# %s\n" % (_h2[i_h2][1]))
      i_h2 += 1
    # Code point/range data.
    props = _props[i]
    # Omit ranges with only default+block properties.
    if props:
      WriteFieldsRangeProps(["cp"], start, end, props, out_file)

# Preprocessing ------------------------------------------------------------ ***

_strip_re = re.compile("([0-9a-fA-F]+.+?) *#.*")
_code_point_re = re.compile("\s*([0-9a-fA-F]+)\s*;")

def CopyAndStripWithOptionalMerge(s, t, do_merge):
  # TODO: With Python 2.7+, combine the two with statements into one.
  with open(s, "r") as in_file:
    with open(t, "w") as out_file:
      first = -1  # First code point with first_data.
      last = -1  # Last code point with first_data.
      first_data = ""  # Common data for code points [first..last].
      for line in in_file:
        match = _strip_re.match(line)
        if match:
          line = match.group(1)
        else:
          line = line.rstrip()
        if do_merge:
          match = _code_point_re.match(line)
          if match:
            c = int(match.group(1), 16)
            data = line[match.end() - 1:]
          else:
            c = -1
            data = ""
          if last >= 0 and (c != (last + 1) or data != first_data):
            # output the current range
            if first == last:
              out_file.write("%04X%s\n" % (first, first_data))
            else:
              out_file.write("%04X..%04X%s\n" % (first, last, first_data))
            first = -1
            last = -1
            first_data = ""
          if c < 0:
            # no data on this line, output as is
            out_file.write(line)
            out_file.write("\n")
          else:
            # data on this line, store for possible range compaction
            if last < 0:
              # set as the first line in a possible range
              first = c
              last = c
              first_data = data
            else:
              # must be c == (last + 1) and data == first_data
              # because of previous conditions
              # continue with the current range
              last = c
        else:
          # Only strip, don't merge: just output the stripped line.
          out_file.write(line)
          out_file.write("\n")
      if do_merge and last >= 0:
        # output the last range in the file
        if first == last:
          out_file.write("%04X%s\n" % (first, first_data))
        else:
          out_file.write("%04X..%04X%s\n" % (first, last, first_data))
        first = -1
        last = -1
        first_data = ""
      out_file.flush()
  return t


def CopyAndStrip(s, t):
  """Copies a file and removes comments behind data lines but not in others."""
  return CopyAndStripWithOptionalMerge(s, t, False)


def CopyAndStripAndMerge(s, t):
  """Copies and strips a file and merges lines.

  Copies a file, removes comments, and
  merges lines with adjacent code point ranges and identical per-code point
  data lines into one line with range syntax.
  """
  return CopyAndStripWithOptionalMerge(s, t, True)


def PrependBOM(s, t):
  # TODO: With Python 2.7+, combine the two with statements into one.
  with open(s, "r") as in_file:
    with open(t, "w") as out_file:
      out_file.write("\xef\xbb\xbf")  # UTF-8 BOM for ICU svn
      shutil.copyfileobj(in_file, out_file)
  return t


def CopyOnly(s, t):
  shutil.copy(s, t)
  return t


def DontCopy(s, t):
  return s


# Each _files value is a
# (preprocessor, dest_folder, parser, order) tuple
# where all fields except the preprocessor are optional.
# After the initial preprocessing (copy/strip/merge),
# if a parser is specified, then a tuple is added to _files_to_parse
# at index "order" (default order 9).
# An explicit order number is set only for files that must be parsed
# before others.
_files = {
  "BidiMirroring.txt": (CopyOnly, ParseBidiMirroring),
  "BidiTest.txt": (CopyOnly, "testdata"),
  "Blocks.txt": (CopyOnly, ParseBlocks),
  "CaseFolding.txt": (CopyOnly, ParseCaseFolding),
  "DerivedAge.txt": (CopyOnly, ParseDerivedAge),
  "DerivedBidiClass.txt": (CopyOnly, ParseDerivedBidiClass),
  "DerivedCoreProperties.txt": (CopyAndStrip, ParseNamedProperties),
  "DerivedJoiningGroup.txt": (CopyOnly, ParseDerivedJoiningGroup),
  "DerivedJoiningType.txt": (CopyOnly, ParseDerivedJoiningType),
  "DerivedNormalizationProps.txt": (CopyAndStrip, ParseNamedProperties),
  "DerivedNumericValues.txt": (CopyOnly, ParseDerivedNumericValues),
  "EastAsianWidth.txt": (CopyAndStripAndMerge, ParseEastAsianWidth),
  "GraphemeBreakProperty.txt": (CopyAndStrip, ParseGraphemeBreakProperty),
  "GraphemeBreakTest.txt": (PrependBOM, "testdata"),
  "IndicMatraCategory.txt": (DontCopy, ParseIndicMatraCategory),
  "IndicSyllabicCategory.txt": (DontCopy, ParseIndicSyllabicCategory),
  "LineBreak.txt": (CopyAndStripAndMerge, ParseLineBreak),
  "LineBreakTest.txt": (PrependBOM, "testdata"),
  "NameAliases.txt": (CopyOnly, ParseNameAliases),
  "NamesList.txt": (DontCopy, ParseNamesList),
  "NormalizationCorrections.txt": (CopyOnly,),  # Only used in gensprep.
  "NormalizationTest.txt": (CopyAndStrip,),
  "PropertyAliases.txt": (CopyOnly, ParsePropertyAliases, 0),
  "PropertyValueAliases.txt": (CopyOnly, ParsePropertyValueAliases, 1),
  "PropList.txt": (CopyAndStrip, ParseNamedProperties),
  "SentenceBreakProperty.txt": (CopyAndStrip, ParseSentenceBreak),
  "SentenceBreakTest.txt": (PrependBOM, "testdata"),
  "Scripts.txt": (CopyAndStrip, ParseScripts),
  "ScriptExtensions.txt": (CopyOnly, ParseScriptExtensions),
  "SpecialCasing.txt": (CopyOnly, ParseSpecialCasing),
  "UnicodeData.txt": (CopyOnly, ParseUnicodeData, 2),
  "WordBreakProperty.txt": (CopyAndStrip, ParseWordBreak),
  "WordBreakTest.txt": (PrependBOM, "testdata")
}

# List of lists of files to be parsed in order.
# Inner lists contain (basename, path, parser) tuples.
_files_to_parse = [[], [], [], [], [], [], [], [], [], []]

# Get the standard basename from a versioned filename.
# For example, match "UnicodeData-6.1.0d8.txt"
# so we can turn it into "UnicodeData.txt".
_file_version_re = re.compile("([a-zA-Z0-9]+)" +
                              "-[0-9]+(?:\\.[0-9]+)*(?:d[0-9]+)?" +
                              "(\\.[a-z]+)$")

def PreprocessFiles(source_files, icu_src_root):
  unidata_path = os.path.join(icu_src_root, "source", "data", "unidata")
  testdata_path = os.path.join(icu_src_root, "source", "test", "testdata")
  folder_to_path = {
    "unidata": unidata_path,
    "testdata": testdata_path
  }
  files_processed = set()
  for source_file in source_files:
    basename = os.path.basename(source_file)
    match = _file_version_re.match(basename)
    if match:
      basename = match.group(1) + match.group(2)
      print "Preprocessing %s" % basename
    if basename in _files:
      if basename in files_processed:
        raise Exception("duplicate file basename %s!" % basename)
      files_processed.add(basename)
      value = _files[basename]
      preprocessor = value[0]
      if len(value) >= 2 and isinstance(value[1], (str, unicode)):
        # The value was [preprocessor, dest_folder, ...], leave [...].
        dest_folder = value[1]
        value = value[2:]
      else:
        # The value was [preprocessor, ...], leave [...].
        dest_folder = "unidata"
        value = value[1:]
      dest_path = folder_to_path[dest_folder]
      if not os.path.exists(dest_path): os.makedirs(dest_path)
      dest_file = os.path.join(dest_path, basename)
      parse_file = preprocessor(source_file, dest_file)
      if value:
        order = 9 if len(value) < 2 else value[1]
        _files_to_parse[order].append((basename, parse_file, value[0]))

# Character names ---------------------------------------------------------- ***

# TODO: Turn this script into a module that
# a) gives access to the parsed data
# b) has a PreparseUCD(ucd_root, icu_src_root) function
# c) has a ParsePreparsedUCD(filename) function
# d) has a WritePreparsedUCD(filename) function
# and then use it from a new script for names.
# Some more API:
# - generator GetRangesAndProps() -> (start, end, props)*

def IncCounter(counters, key, inc=1):
  if key in counters:
    counters[key] += inc
  else:
    counters[key] = inc


endings = (
  # List PHASE- before LETTER for BAMUM LETTER PHASE-xyz.
  "PHASE-",
  "LETTER ", "LIGATURE ", "CHARACTER ", "SYLLABLE ",
  "CHOSEONG ", "JUNGSEONG ", "JONGSEONG ",
  "SYLLABICS ", "IDEOGRAPH ", "IDEOGRAPH-", "IDEOGRAM ", "MONOGRAM ",
  "ACROPHONIC ", "HIEROGLYPH ",
  "DIGIT ", "NUMBER ", "NUMERAL ", "FRACTION ",
  "PUNCTUATION ", "SIGN ", "SYMBOL ",
  "TILE ", "CARD ", "FACE ",
  "ACCENT ", "POINT ",
  # List SIGN before VOWEL to catch "vowel sign".
  "VOWEL ", "TONE ", "RADICAL ",
  # For names of math symbols,
  # e.g., MATHEMATICAL BOLD ITALIC CAPITAL A
  "SCRIPT ", "FRAKTUR ", "MONOSPACE ",
  "ITALIC ", "BOLD ", "DOUBLE-STRUCK ", "SANS-SERIF ",
  "INITIAL ", "TAILED ", "STRETCHED ", "LOOPED ",
  # BRAILLE PATTERN DOTS-xyz
  "DOTS-",
  "SELECTOR ", "SELECTOR-"
)

def SplitName(name, tokens):
  start = 0
  for e in endings:
    i = name.find(e)
    if i >= 0:
      start = i + len(e)
      token = name[:start]
      IncCounter(tokens, token)
      break
  for i in xrange(start, len(name)):
    c = name[i]
    if c == ' ' or c == '-':
      token = name[start:i + 1]
      IncCounter(tokens, token)
      start = i + 1
  IncCounter(tokens, name[start:])


def PrintNameStats():
  # TODO: This name analysis code is out of date.
  # It needs to consider the multi-type Name_Alias values.
  name_pnames = ("na", "na1", "Name_Alias")
  counts = {}
  for pname in name_pnames:
    counts[pname] = 0
  total_lengths = counts.copy()
  max_length = 0
  max_per_cp = 0
  name_chars = set()
  num_digits = 0
  token_counters = {}
  char_counters = {}
  for i in xrange(len(_starts) - 1):
    start = _starts[i]
    # end = _starts[i + 1] - 1
    props = _props[i]
    per_cp = 0
    for pname in name_pnames:
      if pname in props:
        counts[pname] += 1
        name = props[pname]
        total_lengths[pname] += len(name)
        name_chars |= set(name)
        if len(name) > max_length: max_length = len(name)
        per_cp += len(name) + 1
        if per_cp > max_per_cp: max_per_cp = per_cp
        tokens = SplitName(name, token_counters)
        for c in name:
          if c in "0123456789": num_digits += 1
          IncCounter(char_counters, c)
  print
  for pname in name_pnames:
    print ("'%s' character names: %d / %d bytes" %
           (pname, counts[pname], total_lengths[pname]))
  print "%d total bytes in character names" % sum(total_lengths.itervalues())
  print ("%d name-characters: %s" %
         (len(name_chars), "".join(sorted(name_chars))))
  print "%d digits 0-9" % num_digits
  count_chars = [(count, c) for (c, count) in char_counters.iteritems()]
  count_chars.sort(reverse=True)
  for cc in count_chars:
    print "name-chars: %6d * '%s'" % cc
  print "max. name length: %d" % max_length
  print "max. length of all (names+NUL) per cp: %d" % max_per_cp

  token_lengths = sum([len(t) + 1 for t in token_counters])
  print ("%d total tokens, %d bytes with NUL" %
         (len(token_counters), token_lengths))

  counts_tokens = []
  for (token, count) in token_counters.iteritems():
    # If we encode a token with a 1-byte code, then we save len(t)-1 bytes each time
    # but have to store the token string itself with a length or terminator byte,
    # plus a 2-byte entry in an token index table.
    savings = count * (len(token) - 1) - (len(token) + 1 + 2)
    if savings > 0:
      counts_tokens.append((savings, count, token))
  counts_tokens.sort(reverse=True)
  print "%d tokens might save space with 1-byte codes" % len(counts_tokens)

  # Codes=bytes, 40 byte values for name_chars.
  # That leaves 216 units for 1-byte tokens or lead bytes of 2-byte tokens.
  # Make each 2-byte token the token string index itself, rather than
  # and index into a string index table.
  # More lead bytes but also more savings.
  num_units = 256
  max_lead = (token_lengths + 255) / 256
  max_token_units = num_units - len(name_chars)
  results = []
  for num_lead in xrange(min(max_lead, max_token_units) + 1):
    max1 = max_token_units - num_lead
    ct = counts_tokens[:max1]
    tokens1 = set([t for (s, c, t) in ct])
    for (token, count) in token_counters.iteritems():
      if token in tokens1: continue
      # If we encode a token with a 2-byte code, then we save len(t)-2 bytes each time
      # but have to store the token string itself with a length or terminator byte.
      savings = count * (len(token) - 2) - (len(token) + 1)
      if savings > 0:
        ct.append((savings, count, token))
    ct.sort(reverse=True)
    # A 2-byte-code-token index cannot be limit_t_lengths or higher.
    limit_t_lengths = num_lead * 256
    token2_index = 0
    for i in xrange(max1, len(ct)):
      if token2_index >= limit_t_lengths:
        del ct[i:]
        break
      token2_index += len(ct[i][2]) + 1
    cumul_savings = sum([s for (s, c, t) in ct])
    # print ("%2d 1-byte codes: %4d tokens might save %6d bytes" %
    #        (max1, len(ct), cumul_savings))
    results.append((cumul_savings, max1, ct))
  best = max(results)  # (cumul_savings, max1, ct)

  max1 = best[1]
  print ("maximum savings: %d bytes with %d 1-byte codes & %d lead bytes" %
         (best[0], max1, max_token_units - max1))
  counts_tokens = best[2]
  cumul_savings = 0
  for i in xrange(len(counts_tokens)):
    n = 1 if i < max1 else 2
    i1 = i + 1
    t = counts_tokens[i]
    cumul_savings += t[0]
    if i1 <= 250 or (i1 % 100) == 0 or i1 == len(counts_tokens):
      print (("%04d. cumul. %6d bytes save %6d bytes from " +
              "%5d * %d-byte token for %2d='%s'") %
          (i1, cumul_savings, t[0], t[1], n, len(t[2]), t[2]))

# ICU API ------------------------------------------------------------------ ***

# Sample line to match:
#    USCRIPT_LOMA   = 139,/* Loma */
_uscript_re = re.compile(
    " *(USCRIPT_[A-Z_]+) *= *[0-9]+ *, */\* *([A-Z][a-z]{3}) *\*/")

def ParseUScriptHeader(icu_src_root):
  uscript_path = os.path.join(icu_src_root, "source",
                              "common", "unicode", "uscript.h")
  short_script_name_to_enum = _properties["sc"][2]
  scripts_not_in_ucd = set()
  with open(uscript_path, "r") as uscript_file:
    for line in uscript_file:
      match = _uscript_re.match(line)
      if match:
        (script_enum, script_code) = match.group(1, 2)
        if script_code not in short_script_name_to_enum:
          scripts_not_in_ucd.add(script_code)
        else:
          short_script_name_to_enum[script_code] = script_enum
  if scripts_not_in_ucd:
    raise ValueError("uscript.h has UScript constants for scripts "
                     "not in the UCD nor in ISO 15924: %s" % scripts_not_in_ucd)


# Sample line to match:
#    UCHAR_UNIFIED_IDEOGRAPH=29,
_uchar_re = re.compile(
    " *(UCHAR_[0-9A-Z_]+) *= *(?:[0-9]+|0x[0-9a-fA-F]+),")

# Sample line to match:
#    /** Zs @stable ICU 2.0 */
_gc_comment_re = re.compile(" */\*\* *([A-Z][a-z]) *")

# Sample line to match:
#    U_SPACE_SEPARATOR         = 12,
_gc_re = re.compile(" *(U_[A-Z_]+) *= *[0-9]+,")

# Sample line to match:
#    /** L @stable ICU 2.0 */
_bc_comment_re = re.compile(" */\*\* *([A-Z]{1,3}) *")

# Sample line to match:
#    U_LEFT_TO_RIGHT               = 0,
_bc_re = re.compile(" *(U_[A-Z_]+) *= *[0-9]+,")

# Sample line to match:
#    UBLOCK_CYRILLIC =9, /*[0400]*/
_ublock_re = re.compile(" *(UBLOCK_[0-9A-Z_]+) *= *[0-9]+,")

# Sample line to match:
#    U_EA_AMBIGUOUS, /*[A]*/
_prop_and_value_re = re.compile(
    " *(U_(DT|EA|GCB|HST|LB|JG|JT|NT|SB|WB)_([0-9A-Z_]+))")

# Sample line to match if it has matched _prop_and_value_re
# (we want to exclude aliases):
#    U_JG_HAMZA_ON_HEH_GOAL=U_JG_TEH_MARBUTA_GOAL,
_prop_and_alias_re = re.compile(" *U_[0-9A-Z_]+ *= *U")

def ParseUCharHeader(icu_src_root):
  uchar_path = os.path.join(icu_src_root, "source",
                            "common", "unicode", "uchar.h")
  with open(uchar_path, "r") as uchar_file:
    mode = ""
    prop = None
    comment_value = "??"
    for line in uchar_file:
      # Parse some enums via context-sensitive "modes".
      # Necessary because the enum constant names do not contain
      # enough information.
      if "enum UCharCategory" in line:
        mode = "gc"
        prop = _properties["gc"]
        continue
      if mode == "gc":
        # Leave the normal short-to-enum map which is shared between gc & gcm
        # with enums like U_GC_ZS_MASK.
        # For writing gc enums to pnames_data.h use _gc_vname_to_enum.
        if line.startswith("}"):
          mode = ""
          continue
        match = _gc_comment_re.match(line)
        if match:
          comment_value = match.group(1)
          continue
        match = _gc_re.match(line)
        if match:
          gc_enum = match.group(1)
          vname = GetShortPropertyValueName(prop, comment_value)
          _gc_vname_to_enum[vname] = gc_enum
        continue
      if "enum UCharDirection {" in line:
        mode = "bc"
        prop = _properties["bc"]
        comment_value = "??"
        continue
      if mode == "bc":
        if line.startswith("}"):
          mode = ""
          continue
        match = _bc_comment_re.match(line)
        if match:
          comment_value = match.group(1)
          continue
        match = _bc_re.match(line)
        if match:
          bc_enum = match.group(1)
          vname = GetShortPropertyValueName(prop, comment_value)
          prop[2][vname] = bc_enum
        continue
      # No mode, parse enum constants whose names contain
      # enough information to parse without requiring context.
      match = _uchar_re.match(line)
      if match:
        prop_enum = match.group(1)
        if prop_enum.endswith("_LIMIT"):
          # Ignore "UCHAR_BINARY_LIMIT=57," etc.
          continue
        pname = GetShortPropertyName(prop_enum[6:])
        _property_name_to_enum[pname] = prop_enum
        continue
      match = _ublock_re.match(line)
      if match:
        prop_enum = match.group(1)
        if prop_enum == "UBLOCK_COUNT":
          continue
        prop = _properties["blk"]
        vname = GetShortPropertyValueName(prop, prop_enum[7:])
        prop[2][vname] = prop_enum
        continue
      match = _prop_and_value_re.match(line)
      if match:
        (prop_enum, vname) = match.group(1, 3)
        if vname == "COUNT" or _prop_and_alias_re.match(line):
          continue
        prop = GetProperty(match.group(2))
        vname = GetShortPropertyValueName(prop, vname)
        prop[2][vname] = prop_enum
  # No need to parse predictable General_Category_Mask enum constants.
  short_gcm_name_to_enum = _properties["gcm"][2]
  for value in short_gcm_name_to_enum:
    short_gcm_name_to_enum[value] = "U_GC_" + value.upper() + "_MASK"
  # Hardcode known values for the normalization quick check properties,
  # see unorm2.h for the UNormalizationCheckResult enum.
  short_name_to_enum = _properties["NFC_QC"][2]
  short_name_to_enum["N"] = "UNORM_NO"
  short_name_to_enum["Y"] = "UNORM_YES"
  short_name_to_enum["M"] = "UNORM_MAYBE"
  short_name_to_enum = _properties["NFKC_QC"][2]
  short_name_to_enum["N"] = "UNORM_NO"
  short_name_to_enum["Y"] = "UNORM_YES"
  short_name_to_enum["M"] = "UNORM_MAYBE"
  # No "maybe" values for NF[K]D.
  short_name_to_enum = _properties["NFD_QC"][2]
  short_name_to_enum["N"] = "UNORM_NO"
  short_name_to_enum["Y"] = "UNORM_YES"
  short_name_to_enum = _properties["NFKD_QC"][2]
  short_name_to_enum["N"] = "UNORM_NO"
  short_name_to_enum["Y"] = "UNORM_YES"


def WritePNamesDataHeader(out_path):
  # Build a sorted list of (key0, enum) tuples
  # to emulate the output order of the old genpname/preparse.pl.
  #   key0 is either a preparse.pl property type string (for property names)
  #        or a Unicode short property name (for property value names).
  #   enum is the ICU4C enum constant name.
  # TODO: rename prop to not collide with usual properties[x]
  # TODO: once we are sure this works, simplify the order;
  #       for example, change all "_bp" etc. to just ""
  #       (outputs property names first in enum order),
  #       and sorting ccc by numbers not strings
  # TODO: simplify further, to make pnames_data.h more stable;
  #       try not to print string or group index numbers
  # TODO: wiki/ReviewTicket8972 with diff links
  prop_type_to_old_type = {
    "Binary": "_bp",
    "Bitmask": "_op",
    "Catalog": "_ep",
    "Enumerated": "_ep",
    "Miscellaneous": "_sp",
    "Numeric": "_dp",
    "String": "_sp"
  }
  pnames_data = [("binprop", "0"), ("binprop", "1")]
  # Only properties that have ICU API.
  missing_enums = []
  for (pname, prop_enum) in _property_name_to_enum.iteritems():
    prop = _properties[pname]
    # Sometimes the uchar.h UProperty type differs
    # from the PropertyAliases.txt type.
    if pname == "age":
      type = "_sp"
    elif pname in ("gcm", "scx"):
      type = "_op"
    else:
      type = prop_type_to_old_type[prop[0]]
    pnames_data.append((type, prop_enum))
    if type != "_bp" and pname != "age":
      short_name_to_enum = prop[2]
      if pname.endswith("ccc"):
        # ccc, lccc, tccc use the string forms of their numeric values
        # as "enum" values.
        # In the UCD data, these numeric strings are the first value names,
        # followed by the short & long value names.
        for name in short_name_to_enum:
          pnames_data.append((pname, name))
      else:
        if pname == "gc":
          # See comment about _gc_vname_to_enum in ParseUCharHeader().
          short_name_to_enum = _gc_vname_to_enum
        for (name, enum) in short_name_to_enum.iteritems():
          if enum:
            pnames_data.append((pname, enum))
          else:
            missing_enums.append((pname, name))
  if missing_enums:
    raise ValueError(
        "missing uchar.h enum constants for some property values: %s" %
        missing_enums)
  pnames_data.sort()
  for item in pnames_data:
    print item
  short_script_name_to_enum = _properties["sc"][2]
  # print short_script_name_to_enum
  # print _property_name_to_enum
  # print _properties["ea"][2]
  # print _properties["gcm"][2]

# main() ------------------------------------------------------------------- ***

def main():
  global _null_or_defaults
  if len(sys.argv) < 4:
    print ("Usage: %s  path/to/UCD/root  path/to/ICU/src/root  "
           "path/to/ICU/tools/root" % sys.argv[0])
    return
  (ucd_root, icu_src_root, icu_tools_root) = sys.argv[1:4]
  source_files = []
  for root, dirs, files in os.walk(ucd_root):
    for file in files:
      source_files.append(os.path.join(root, file))
  PreprocessFiles(source_files, icu_src_root)
  # Parse the processed files in a particular order.
  for files in _files_to_parse:
    for (basename, path, parser) in files:
      print "Parsing %s" % basename
      value = _files[basename]
      if basename == "NamesList.txt":
        in_file = codecs.open(path, "r", "ISO-8859-1")
      else:
        in_file = open(path, "r")
      with in_file:
        parser(in_file)
  _null_or_defaults = _null_values.copy()
  _null_or_defaults.update(_defaults)
  # Every Catalog and Enumerated property must have a default value,
  # from a @missing line. "nv" = "null value".
  pnv = [pname for (pname, nv) in _null_or_defaults.iteritems() if nv == "??"]
  if pnv:
    raise Exception("no default values (@missing lines) for " +
                    "some Catalog or Enumerated properties: %s " % pnv)
  # Optimize block vs. cp properties.
  CompactBlocks()
  # Write the ppucd.txt output file.
  unidata_path = os.path.join(icu_src_root, "source", "data", "unidata")
  if not os.path.exists(unidata_path): os.makedirs(unidata_path)
  out_path = os.path.join(unidata_path, "ppucd.txt")
  with open(out_path, "w") as out_file:
    WritePreparsedUCD(out_file)
    out_file.flush()
  # TODO: PrintNameStats()
  # ICU data for property & value names API
  ParseUScriptHeader(icu_src_root)
  ParseUCharHeader(icu_src_root)
  genprops_path = os.path.join(icu_tools_root, "unicode", "c", "genprops")
  if not os.path.exists(genprops_path): os.makedirs(genprops_path)
  out_path = os.path.join(genprops_path, "pnames_data.h")
  WritePNamesDataHeader(out_path)


if __name__ == "__main__":
  main()
