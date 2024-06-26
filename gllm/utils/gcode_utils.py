import re
import os
import pygcode
import tempfile
import subprocess
import streamlit as st
from utils.plot_utils import plot_gcode, parse_coordinates
from utils.prompts_utils import REQUIRED_PARAMETERS
from langchain_core.messages.ai import AIMessage



def generate_gcode_logic(chain):
    if any(param not in st.session_state['user_inputs'] for param in REQUIRED_PARAMETERS):
        print(st.session_state['user_inputs'])
        st.error("Please provide all the required parameters.")
    else:        
        gcode = generate_gcode_with_langchain(chain, st.session_state['user_inputs'])
        cleaned_gcode = clean_gcode(gcode)
        st.session_state['gcode'] = cleaned_gcode

def generate_gcode_with_langchain(chain, user_inputs):
    final_prompt = (
        "Based on the details provided, generate a robust G-code for the CNC machining operation:\n\n"
        f"Material: {user_inputs['Material']}\n"
        f"Operation Details:\n"
        f"Operation Type: {user_inputs['Operation Type']}\n"
        f"Desired Shape: {user_inputs['Desired Shape']}\n"
        f"Home Position: {user_inputs['Home Position']}\n"
        f"Return Tool to Home After Execution: {user_inputs['Return Tool to Home After Execution']}\n"
        f"Starting Point: {user_inputs['Starting Point']}\n"
        f"Cutting Tool Path: {user_inputs['Cutting Tool Path']}\n"
        f"Workpiece Dimensions: {user_inputs['Workpiece Dimensions']}\n"
        f"Depth of Cut: {user_inputs['Depth of Cut']}\n"
        f"Feed Rate: {user_inputs['Feed Rate']}\n"
        f"Spindle Speed: {user_inputs['Spindle Speed']}\n"
   )
    gcode_response = chain.invoke({'input':final_prompt})
    return gcode_response

def clean_gcode(gcode):
    gcode_response = gcode.content if isinstance(gcode, AIMessage) else str(gcode)
    gcode_pattern = re.compile(r"^(?:G|M|T|F|S|X|Y|Z|I|J|K|R|P|Q)\d+.*")
    cleaned_lines = [line.strip() for line in gcode_response.split('\n') if gcode_pattern.match(line)]
    return '\n'.join(cleaned_lines)

def display_generated_gcode():
    if st.session_state['gcode']:
        st.subheader("Generated G-code")
        st.text_area("G-code:", st.session_state['gcode'], height=300)
        st.download_button(
            label="Download G-code",
            data=st.session_state['gcode'],
            file_name="generated.gcode",
            mime="text/plain")

def plot_generated_gcode():
    if st.button("Plot G-code"):
        plt = plot_gcode(st.session_state['gcode'])
        st.pyplot(plt)

def validate_syntax(gcode_string):
    """Parsing G-code and checking for syntax errors."""
    try:
        for line in gcode_string.splitlines():
            gcode_line = pygcode.Line(line)
            for word in gcode_line.block.gcodes:
                # Validate that the word is a valid G-code command
                if not isinstance(word, pygcode.gcodes.GCode):
                    error_msg = f"Invalid G-code command: {word}"
                    raise ValueError(error_msg)
        return True, None
    except Exception as e:
        print(f"Syntax error in G-code: {e}")
        return False, e

def validate_unreachable_code(gcode_string):
    """Detecting unreachable code in the program"""
    reached_end = False
    for line_text in gcode_string.strip().split('\n'):
        if 'M30' in line_text:
            reached_end = True
        elif reached_end:
            error_msg = f"Unreachable code detected: {line_text}"
            print(error_msg)
            return False, error_msg
        else:
            print(f"Executed: {line_text}")

    return True, None 

def validate_safety(gcode_string):
    """Ensuring that rapid movements do not pass through the material"""
    is_cutting = False
    for line_text in gcode_string.strip().split('\n'):
        if 'G1' in line_text or 'G01' in line_text:
            is_cutting = True
        if ('G0 ' in line_text or 'G00' in line_text) and is_cutting:
            error_msg = f"Warning: Rapid movement through potential material at {line_text}"
            print(error_msg)
            return False, error_msg
        if is_cutting:
            is_cutting = False
        print(f"Processed: {line_text}")
    
    return True, None

def validate_continuity(gcode_string):
    """Checking for continuity in tool paths"""
    lines = gcode_string.strip().split('\n')
    last_position = {'X': 0, 'Y': 0, 'Z': 0}  # Initial tool position (assuming starting at origin)


    for line_text in lines:
        line = pygcode.Line(line_text)

        # Extract the G-code command
        commands = line.block.gcodes

        # Extract the X, Y, and Z values, if they exist
        x = line.block.get_param('X')
        y = line.block.get_param('Y')
        z = line.block.get_param('Z')

        # Only update the last_position with the values that are present in the command
        current_position = {
            'X': x if x is not None else last_position['X'],
            'Y': y if y is not None else last_position['Y'],
            'Z': z if z is not None else last_position['Z']
        }

        # If there is a move command (G0 or G1) and the position changes, update last_position
        print(commands)
        if commands and any(cmd.word in ('G0 ', 'G1 ', 'G00', 'G01') for cmd in commands):
            last_position = current_position
            print(last_position, current_position)
        else:
            # If the command is not a move command, we only log the processing information
            print(f"Processed: {line_text}")
            continue
        
        # Check for discontinuity
        if (current_position['X'], current_position['Y'], current_position['Z']) != (last_position['X'], last_position['Y'], last_position['Z']):
            error_msg = f"Discontinuity detected at {line_text}"
            print(error_msg)
            return False, error_msg
        
        print(f"!!Processed: {line_text}")

    return True, None
    #     # Ensure the line has G-code commands and check for X, Y parameters
    #     if line.block.gcodes and 'X' in line.block.gcodes[0].params and 'Y' in line.block.gcodes[0].params:
    #         current_position = (line.block.gcodes[0].params['X'], line.block.gcodes[0].params['Y'])
    #         if last_position and (current_position != last_position):
    #             error_msg = f"Discontinuity detected at {line_text}"
    #             print(error_msg)
    #             return False, error_msg
    #         last_position = current_position
    #     print(f"Processed: {line_text}")
    # return True, None

def validate_feed_rate(gcode_string, min_feed, max_feed):
    """Ensure that the feed rate specified in G-code commands is within the acceptable limits for the material and tool being used. 
       This can prevent tool breakage and suboptimal machining conditions."""
    lines = gcode_string.strip().split('\n')
    for line_text in lines:
        line = pygcode.Line(line_text)
        if 'F' in line.block.modal_params:
            feed_rate = line.block.modal_params['F']
            if not (min_feed <= feed_rate <= max_feed):
                error_msg = f"Feed rate out of bounds at {line_text}"
                print(error_msg)
                return False, error_msg
    return True, None

def validate_tool_changes(gcode_string):
    expecting_initialization = False
    lines = gcode_string.strip().split('\n')
    for line_text in lines:
        line = pygcode.Line(line_text)
        if 'T' in line.block.modal_params:
            expecting_initialization = True
        elif 'S' in line.block.modal_params and expecting_initialization:
            expecting_initialization = False
        elif expecting_initialization:
            error_msg = f"Missing spindle speed after tool change before {line_text}"
            print(error_msg)
            return False, error_msg
    return True, None

def validate_spindle_speed(gcode_string, max_spindle_speed):
    """"Ensure that spindle speeds are within the machine's operational limits."""
    lines = gcode_string.strip().split('\n')
    for line_text in lines:
        line = pygcode.Line(line_text)
        if 'S' in line.block.modal_params:
            spindle_speed = line.block.modal_params['S']
            if spindle_speed > max_spindle_speed:
                error_msg = f"Spindle speed exceeds maximum limit at {line_text}"
                print(error_msg)
                return False, error_msg
    return True, None

def validate_z_levels(gcode_string, max_depth):
    """Verify that Z-level movements do not exceed certain depth limits to prevent the tool from crashing into the workpiece or machine bed."""
    lines = gcode_string.strip().split('\n')
    for line_text in lines:
        line = pygcode.Line(line_text)
        if 'Z' in line.block.gcodes[0].params:
            z_level = line.block.gcodes[0].params['Z']
            if z_level > max_depth:
                error_msg = f"Z-level exceeds maximum depth at {line_text}"
                print(error_msg)
                return False, error_msg
    return True, None


# def check_safe_return(gcode_string, safe_position={'X': -1, 'Y': 0, 'Z': 10}):
#     """
#     Check if the G-code program returns the tool to a safe position at the end.

#     :param gcode_string: The G-code string to be checked.
#     :param safe_position: A dictionary specifying the safe return position.
#     :return: True if the tool returns to the safe position at the end, otherwise False.
#     """
#     # Validate safe position Z value
#     if 'Z' in safe_position and safe_position['Z'] < -1:
#         raise ValueError("Safe position Z value must be zero or positive.")

#     lines = gcode_string.splitlines()
#     positioning_mode = 'G89'  # Default to absolute positioning
#     current_position = {'X': -1, 'Y': 0, 'Z': 0}

#     for line in lines:
#         gcode_line = pygcode.Line(line)
#         for block in gcode_line.block.gcodes:
#             if block.word in ('G89', 'G91'):
#                 positioning_mode = block.word
#             coords = parse_coordinates(line)
#             current_position.update(coords)

#     # Determine if the final position matches the safe position
#     if positioning_mode == 'G90':  # If relative positioning, adjust the check accordingly
#         # We need to consider the relative move to the safe position
#         final_position = {axis: current_position.get(axis, -1) for axis in safe_position}
#         for axis in safe_position:
#             if axis in current_position:
#                 final_position[axis] += safe_position[axis]
#     else:
#         final_position = current_position

#     # Allow Z in final_position to be zero or any positive number
#     is_return_home = all(
#         (axis != 'Z' and final_position.get(axis, -1) == safe_position[axis]) or
#         (axis == 'Z' and final_position.get(axis, -1) >= 0)
#         for axis in safe_position)
    
#     if not is_return_home:
#         error_msg = f"The tool does not return to the home position {safe_position}, where the final position is {final_position}. Make sure to bring the tool up and move it to the home position."
#         #error_msg = f"The tool does not return to a safe position, where the final position is inside the workpiece Z={final_position.get('Z')}. Make sure to bring the tool up and move it to the home position."

#         return is_return_home, error_msg
#     else:
#         return is_return_home, None


def check_tool_offsets(gcode_string):
    """Validate that tool offsets are being used correctly and reset appropriately to avoid unintended tool paths."""
    tool_offset_active = False
    lines = gcode_string.strip().split('\n')
    for line_text in lines:
        line = pygcode.Line(line_text)
        if 'G43' in line_text:  # Tool length offset compensation activate
            tool_offset_active = True
        elif 'G49' in line_text:  # Tool length offset compensation cancel
            tool_offset_active = False
        elif tool_offset_active and 'Z' in line.block.gcodes[0].params:
            error_msg = f"Z movement with active tool offset in line: {line_text}"
            print(error_msg)
            return False, error_msg
    return True, None

def validate_drilling_gcode(gcode_string, safe_height=0):
    """
    Validate that the G-code only drills at specified depths and does not mill between the holes.

    :param gcode_string: The G-code string to be validated.
    :param safe_height: Safe height above the workpiece for rapid movements.
    :return: (bool, str) True and None if the G-code is valid, otherwise False and an error message.
    """
    current_position = {'X': 0, 'Y': 0, 'Z': safe_height}
    lines = gcode_string.strip().split('\n')
    for line in lines:
        gcode_line = pygcode.Line(line)
        for block in gcode_line.block.gcodes:
            if isinstance(block, pygcode.gcodes.GCode):
                coords = parse_coordinates(line)
                if block.word in ('G0', 'G00', 'G1', 'G01'):  # Rapid or linear move
                    if 'Z' in coords and coords['Z'] is not None:
                        current_position['Z'] = coords['Z']

                    if ( (coords.get('X') is not None or coords.get('Y') is not None) and
                            current_position['Z'] < safe_height):
                        error_msg = (f"Invalid horizontal movement detected with G1 command at Z={current_position['Z']} "
                                     f"(below safe height) at position X={current_position['X']}, Y={current_position['Y']}. "
                                     f"Ensure that all horizontal movements occur at or above the safe height (Z >= {safe_height}).")
                        return False, error_msg

                    if 'X' in coords and coords['X'] is not None:
                        current_position['X'] = coords['X']
                    if 'Y' in coords and coords['Y'] is not None:
                        current_position['Y'] = coords['Y']

    return True, None

def validate_gcode(gcode_string):

    is_syntax,_ = validate_syntax(gcode_string)

    is_unreachable_code,_ = validate_unreachable_code(gcode_string)

    is_safe,_ = validate_safety(gcode_string)

    is_continuous,_ = validate_continuity(gcode_string)

    is_valid_feed_rate,_ = validate_feed_rate(gcode_string, min_feed=1, max_feed=100)

    is_valid_tool_change,_ = validate_tool_changes(gcode_string)

    is_valid_spindle_speed,_ = validate_spindle_speed(gcode_string, max_spindle_speed=900)

    #is_return_home = check_return_to_home(gcode_string)
    
    is_tool_offset,_ = check_tool_offsets(gcode_string)

    return True if  is_syntax and \
                    is_unreachable_code and \
                    is_safe and is_continuous and \
                    is_valid_feed_rate and \
                    is_valid_tool_change and \
                    is_tool_offset and \
                    is_valid_spindle_speed else False

