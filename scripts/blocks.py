# Script for generating the block state file (blocks/lib.rs).
# This script reads from the vanilla server's blocks.json data report
# and produces corresponding Rust code.

# Rustfmt should be run on the generated code,
# because proper formatting is not accounted
# for here.

import json
import sys
import re
from collections import OrderedDict


# List of Rust keywords which should
# be suffixed with an underscore when
# used as a variable name
KEYWORDS = [
    "type",
    "in",
]

# These property names are properties
# for which an enum is pre-created.
# This avoids duplicate enums with names
# "DarkOakLogAxis", "OakLogAxis", "BirchLogAxis", etc.
KNOWN_PROPERTIES = [
    "facing",
    "axis",
    "half",
    "face",
    "shape",
    "hinge",
    "part"
]


DERIVES = "#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]\n"

# Strips the "minecraft:" prefix from
# a block identifier, leaving only the snake_case
# block name.
def strip_minecraft_identifier(s):
    return s[10:]


# Converts a snake_case string to
# UpperCamelCase.
def snake_to_upper_camel(s):
    components = s.split("_")
    return "".join(x.title() for x in components)

def get_type_from_value(val):
    if val == "true" or val == "false":
        return "bool"

    if val.isdigit():
        return "i32"

    return "_enum"


# Modifies a state property name
# to make it compatible with Rust.
def process_property_name(s):
    if s in KEYWORDS:
        s += "_"
    return s

in_path = sys.argv[1]
out_path = sys.argv[2]

print("Generating block state code into %s using block state file %", in_path, out_path)

fin = open(in_path, "r+")
fout = open(out_path, "w+")

print("Reading data")

data = json.load(fin, object_pairs_hook=OrderedDict)

enum_code = ""

enum_code += DERIVES + \
        "pub enum Block {\n"

block_state_id_code = ""

block_state_id_code += "pub fn block_state_id(&self) -> u16 {\n" \
                       "match self {"

from_block_state_id_code = ""

from_block_state_id_code += "pub fn from_block_state_id(id: u16) -> Self {\n" \
                            "match id {" \

state_code = ""

end_code = ""

# Code for the function that returns the block state name as a string.
# Whoever decided to use strings instead of numerical global palette IDs
# in the world format should be fired.
name_code = "pub fn name(&self) -> &'static str {\n" \
            "match self {\n"

# Code for the function that returns a map of
# property names to property values, both as nasty,
# inefficient strings.
property_names_code = "pub fn property_names(&self) -> HashMap<&'static str, &'static str> {\n" \
                      "let mut m = HashMap::new();\n" \
                      "match self {\n"


# Known properties - facing and axis
end_code += DERIVES + "pub enum Facing {" \
            "North, South, East, West, Up, Down, }\n\n"

end_code += DERIVES + "pub enum Axis {" \
            "X, Y, Z, }\n\n"

end_code += DERIVES + "pub enum Half {" \
            "Upper, Lower, Top, Bottom, }\n\n"

end_code += DERIVES + "pub enum Face {" \
            "Floor, Wall, Ceiling, }\n\n"

end_code += DERIVES + "pub enum Shape {" \
            "Straight, InnerLeft, InnerRight, OuterLeft, OuterRight, AscendingNorth, AscendingEast, AscendingSouth, " \
                      "AscendingWest, NorthEast, NorthWest, SouthEast, SouthWest, NorthSouth, EastWest,\n\n}"

end_code += DERIVES + "pub enum Hinge {" \
                      "Left, Right, }\n\n"

end_code += DERIVES + "pub enum Part {" \
                      "Head, Foot, }\n\n"

for block_identifier in data:
    print("Reading for block %s", block_identifier)
    block_name = strip_minecraft_identifier(block_identifier)
    print("Block name: %s", block_name)
    obj = data[block_identifier]

    states = obj["states"]
    single_state = len(states) == 1
    camel = snake_to_upper_camel(block_name)

    # Add mapping in name() function
    name_code += "Block::" + camel
    # If block has data, we have to discard it in the match arm
    if not single_state:
        name_code += "(_)"
    name_code += " => \"" + block_identifier + "\",\n"

    if single_state:
        id = str(states[0]["id"])
        enum_code += camel + ",\n"
        block_state_id_code += "Block::" + camel + " => return " + id + ",\n"
        from_block_state_id_code += id + " => return Block::" + camel + ",\n"

    else:
        # Generate a bunch of mappings to account
        # for property data.
        data_struct_name = camel + "Data"
        state_code += DERIVES + "pub struct " + data_struct_name + " {"

        property_names_code += "Block::" + camel + "(data) => {\n"

        props = obj["properties"]
        for prop_name in props:
            vals = props[prop_name]
            ty = get_type_from_value(vals[0])

            if prop_name in KNOWN_PROPERTIES:
                ty = snake_to_upper_camel(prop_name)  # e.g. facing -> Facing, axis -> Axis

            if ty == "_enum":
                # Create enum for custom value type
                ty = camel + snake_to_upper_camel(prop_name)
                end_code += DERIVES + "pub enum " + ty + " {"
                for val in vals:
                    end_code += snake_to_upper_camel(val) + ",\n"
                end_code += "}\n\n"

            prop_name = process_property_name(prop_name)

            state_code += "pub " + prop_name + ": " + ty + ",\n"

            # Generate property mappings as strings.
            # Note that the property enums use
            # UpperCamelCase while Minecraft uses snake_case
            # for property names, so we need to convert
            # to snake_case at runtime. This is performed
            # using the heck crate (https://github.com/withoutboats/heck).
            property_names_code += "m.insert(\"" + prop_name + "\", (&format!(\"{:?}\", data." + prop_name \
                                   + ")).to_snake_case().as_str());"

        state_code += "}\n\n"

        property_names_code += "},\n"

        enum_code += camel + "(" + data_struct_name + "),\n"

        # Conversions between enum values and state ID
        state_if_code = ""
        for state in obj["states"]:
            state_if_code += "if "
            state_props = state["properties"]

            from_block_state_id_code += str(state["id"]) + " => {\nreturn Block::" + camel + "(" + camel + "Data {"

            count = 0
            for prop_name, prop_val in state_props.iteritems():
                rust_prop_val = ""
                ty = get_type_from_value(prop_val)
                if ty == "_enum":
                    if prop_name in KNOWN_PROPERTIES:
                        ty = snake_to_upper_camel(prop_name)
                    else:
                        ty = camel + snake_to_upper_camel(prop_name)
                    prop_val = ty + "::" + snake_to_upper_camel(prop_val)

                if count != 0:
                    state_if_code += " && "
                state_if_code += "data." + process_property_name(prop_name) + " == " + prop_val
                count += 1

                # from_block_state_id_code
                from_block_state_id_code += process_property_name(prop_name) + ": " + prop_val + ",\n"

            state_if_code += "{\n" "return " + str(state["id"]) + ";\n}\n"
            from_block_state_id_code += "});\n},\n"

        block_state_id_code += "Block::" + camel + "(data) => {\n"
        block_state_id_code += state_if_code
        block_state_id_code += "\n}"


enum_code += "}"

from_block_state_id_code += "_ => panic!(\"Unknown block state ID {}\", id),"
from_block_state_id_code += "\n}panic!(\"Invalid block state ID {}\", id);\n}\n"

block_state_id_code += "_ => panic!(\"Invalid block state {:?}\", self),\n}\n"
block_state_id_code += "panic!(\"Invalid block state {:?}\", self);}\n"

# "Simple" blocks - those without properties - don't need an entry
# in the match arm for property_names(), so we can default
# to doing nothing.
property_names_code += "_ => (),\n"

# End of match arm
property_names_code += "}\n"

# Return the map created at the beginning of the function
property_names_code += "m\n"

# End of function
property_names_code += "}\n"

name_code += "}\n}\n"

fout.write("// This file was generated by /scripts/blocks.py\n\n")
fout.write("use std::collections::HashMap;\n")
fout.write("use heck::SnakeCase;\n\n");
fout.write(enum_code)
fout.write("\n")
fout.write("impl Block {\n")
fout.write(block_state_id_code)
fout.write("\n\n")
fout.write(from_block_state_id_code)
fout.write(name_code)
fout.write("\n")
fout.write(property_names_code)

# End of impl block
fout.write("}")

# These are structs + enums outside the impl block
fout.write("\n" + state_code)
fout.write("\n" + end_code)