#ifndef SIGNAL_BOX_SECURITY_PROFILE_H
#define SIGNAL_BOX_SECURITY_PROFILE_H

#include <stdint.h>

uint32_t signal_box_security_critical(void);
uint32_t signal_box_security_debugen(void);
uint32_t signal_box_security_debugen_lock(void);
void signal_box_security_check(void);
void signal_box_security_bootsel(void);

#endif
