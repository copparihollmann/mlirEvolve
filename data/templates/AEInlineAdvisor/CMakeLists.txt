cmake_minimum_required(VERSION 3.20)
project(AEInliner)

# 1. Find LLVM (Assumes you have llvm installed)
find_package(LLVM REQUIRED CONFIG)
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(AddLLVM)

add_definitions(${LLVM_DEFINITIONS})
include_directories(${LLVM_INCLUDE_DIRS})

# 2. Define the Plugin
add_llvm_library(AEInliner MODULE
  AEInlineAdvisor.cpp
  PLUGIN_TOOL opt
)

# 3. Compiler Flags (Speed is key)
set_target_properties(AEInliner PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)