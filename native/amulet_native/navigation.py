"""Deterministic grid navigation and scroll-to-selection geometry."""


def move_cell(index, direction):
    row, column = divmod(index, 16)
    if direction == "left": column = max(0, column - 1)
    elif direction == "right": column = min(15, column + 1)
    elif direction == "up": row = max(0, row - 1)
    elif direction == "down": row = min(15, row + 1)
    elif direction == "home": column = 0
    elif direction == "end": column = 15
    elif direction == "first": row, column = 0, 0
    elif direction == "last": row, column = 15, 15
    return row * 16 + column


def reveal_cell(index, size, viewport_width, viewport_height, current_x, current_y):
    x, y = 36 + index % 16 * size, 36 + index // 16 * size
    def offset(start, extent, current):
        requested = start if start < current else start + size - extent if start + size > current + extent else current
        return min(max(0, 36 + size * 16 - extent), max(0, requested))
    return {"x": offset(x, viewport_width, current_x), "y": offset(y, viewport_height, current_y)}
