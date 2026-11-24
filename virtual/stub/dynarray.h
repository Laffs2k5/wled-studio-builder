// SPDX-License-Identifier: EUPL-1.2
// WLED's linker-section arrays have no WebAssembly equivalent; the virtual WLED registers
// usermods in a list instead (wled.h redefines REGISTER_USERMOD).
#pragma once
#define DYNARRAY_SECTION ".dynarray"
#define DECLARE_DYNARRAY(type, array_name)
#define DYNARRAY_MEMBER(type, array_name, member_name, array_section) type const member_name
