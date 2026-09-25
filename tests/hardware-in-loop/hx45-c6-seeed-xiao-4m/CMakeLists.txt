cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED PULSE_REPO_ROOT)
    get_filename_component(PULSE_REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
endif()

if(NOT EXISTS "${PULSE_REPO_ROOT}/firmware/components/wdc_extension/CMakeLists.txt")
    message(FATAL_ERROR "PULSE_REPO_ROOT does not identify the pulse-esp32-host repository")
endif()

set(EXTRA_COMPONENT_DIRS "${PULSE_REPO_ROOT}/firmware/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(pulse_hx45_c6_xiao_4m)
