#!/usr/bin/env python3
#
# Script to generate a token that can be used as webhook secret
#

import random, string

def gen_pass(length):
    rand = random.SystemRandom()
    chars = string.ascii_letters + string.digits
    return ''.join(rand.choice(chars) for _ in range(length))

print(gen_pass(128))
