/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "pi-idle-policy.h"

int main(void)
{
    pi_idle_policy p = { .last_media_ms=1234, .timeout_ms=600000 };
    assert(pi_idle_step(&p, 601233, 0, 1) == 0);
    assert(pi_idle_step(&p, 601234, 0, 1) == 1);
    assert(p.sleeping);
    /* Hours of status/USB traffic do not constitute media activity. */
    assert(pi_idle_step(&p, 7200000, 0, 1) == 0 && p.sleeping);
    assert(pi_idle_step(&p, 7200001, 1, 1) == -1 && !p.sleeping);
    assert(pi_idle_step(&p, 7800000, 1, 1) == 0);
    assert(pi_idle_step(&p, 7800001, 1, 1) == 1);
    /* Week-long inactivity and crossing SDL's 32-bit tick wrap. */
    assert(pi_idle_step(&p, UINT64_C(5000000000), 1, 1) == 0 && p.sleeping);
    assert(pi_idle_step(&p, UINT64_C(5000000001), 2, 1) == -1);
    assert(pi_idle_step(&p, UINT64_C(5000600000), 2, 1) == 0);
    assert(pi_idle_step(&p, UINT64_C(5000600001), 2, 1) == 1);
    /* Transport changes resume; only the wired project mode is governed. */
    assert(pi_idle_step(&p, UINT64_C(5000600002), 2, 0) == -1);
    assert(pi_idle_step(&p, UINT64_C(5001600002), 2, 0) == 0);
    p.timeout_ms = 0;
    assert(pi_idle_step(&p, UINT64_C(6000000000), 2, 1) == 0);
    /* Media before the boundary restarts the entire grace period. */
    p = (pi_idle_policy){ .timeout_ms=600000 };
    assert(pi_idle_step(&p, 599999, 1, 1) == 0);
    assert(pi_idle_step(&p, 600000, 1, 1) == 0);
    assert(pi_idle_step(&p, 1199998, 1, 1) == 0);
    assert(pi_idle_step(&p, 1199999, 1, 1) == 1);
    /* Activity generation wraps safely; no wall-clock dependence. */
    p.media_serial = UINT32_MAX;
    assert(pi_idle_step(&p, 1200000, 0, 1) == -1);
    puts("idle policy: 600 s boundary, activity, week/wrap, transport and disable PASS");
    return 0;
}
