cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED PULSE_REPO_ROOT)
    message(FATAL_ERROR "PULSE_REPO_ROOT must identify the staged HP5.5 source tree")
endif()
if(NOT EXISTS "${PULSE_REPO_ROOT}/firmware/components/wdc_http/CMakeLists.txt")
    message(FATAL_ERROR "PULSE_REPO_ROOT does not contain the HP5 network components")
endif()

set(EXTRA_COMPONENT_DIRS "${PULSE_REPO_ROOT}/firmware/components")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(pulse_hp5_5_network_admin)
