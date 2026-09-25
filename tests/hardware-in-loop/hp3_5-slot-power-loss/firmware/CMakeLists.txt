cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED PULSE_REPO_ROOT)
    message(FATAL_ERROR "PULSE_REPO_ROOT must identify the staged Pulse source tree")
endif()

if(NOT EXISTS "${PULSE_REPO_ROOT}/firmware/components/wdc_app_slots/CMakeLists.txt")
    message(FATAL_ERROR "PULSE_REPO_ROOT does not contain the HP3 application-slot components")
endif()

set(EXTRA_COMPONENT_DIRS "${PULSE_REPO_ROOT}/firmware/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(pulse_hp3_5_slot_hardware)
