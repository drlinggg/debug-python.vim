def inner(a):
    b = a + 1
    return b


def outer():
    x = 1
    y = inner(x)
    z = y + 1
    return z


def boom():
    k = 41
    return k / 0        # line 15: raises ZeroDivisionError
