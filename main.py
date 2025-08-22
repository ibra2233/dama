# main.py
from kivy.app import App
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.properties import NumericProperty, ListProperty, ObjectProperty
from kivy.clock import Clock
import math
import random

def clamp(x, lo=0, hi=255):
    return max(lo, min(hi, int(x)))

class BoardWidget(Widget):
    board = ListProperty()
    turn = NumericProperty(1)
    selected = ObjectProperty(allownone=True)       # (row, col) أو None
    pending_sequences = ObjectProperty(allownone=True)
    highlights = ListProperty()                     # [(r,c),...]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # لوح البداية (نفس pygame: القطع على الخانات الداكنة والصفوف العليا/السفلى)
        self.board = [[None for _ in range(8)] for _ in range(8)]
        for row in range(8):
            for col in range(8):
                if (row + col) % 2 == 0:
                    if row < 3:
                        self.board[row][col] = {'player': 1, 'king': False}
                    elif row > 4:
                        self.board[row][col] = {'player': 2, 'king': False}

        self.bind(size=self._trigger_redraw, pos=self._trigger_redraw)
        self._trigger_redraw()

    # ======= مقاييس الرسم =======
    def _metrics(self):
        W, H = self.width, self.height
        square_size = int(min(W, H) * 0.9)
        square_x = int(self.x + (W - square_size) // 2)
        square_y = int(self.y + (H - square_size) // 2)
        cell_size = square_size // 8
        piece_radius = max(8, cell_size // 2 - 10)
        return square_x, square_y, square_size, cell_size, piece_radius

    def get_cell_center(self, col, row):
        # نرسم الصف 0 في الأعلى كما في pygame: لذا نقلب الإسقاط على محور y
        square_x, square_y, _, cell_size, _ = self._metrics()
        x = square_x + col * cell_size + cell_size // 2
        y = square_y + (7 - row) * cell_size + cell_size // 2
        return x, y

    def in_bounds(self, r, c):
        return 0 <= r < 8 and 0 <= c < 8

    # ======= المنطق: سلاسل الأكل (الرجل لا يأكل للخلف) =======
    def get_jumps(self, piece, row, col, visited_captures=None):
        board = self.board
        if visited_captures is None:
            visited_captures = set()
        jumps = []
        directions = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        for dr, dc in directions:
            if not piece['king']:
                if piece['player'] == 1 and dr == -1:
                    continue
                if piece['player'] == 2 and dr == 1:
                    continue
                mid_r, mid_c = row + dr, col + dc
                land_r, land_c = row + 2*dr, col + 2*dc
                if not self.in_bounds(mid_r, mid_c) or not self.in_bounds(land_r, land_c):
                    continue
                mid_piece = board[mid_r][mid_c]
                if (mid_piece and mid_piece['player'] != piece['player']
                        and board[land_r][land_c] is None
                        and (mid_r, mid_c) not in visited_captures):
                    new_visited = set(visited_captures)
                    new_visited.add((mid_r, mid_c))
                    further = self.get_jumps(piece, land_r, land_c, new_visited)
                    if further:
                        for seq in further:
                            jumps.append([(land_r, land_c, mid_r, mid_c)] + seq)
                    else:
                        jumps.append([(land_r, land_c, mid_r, mid_c)])
            else:
                # الملك يأكل بعيد (طويل)
                step = 1
                while True:
                    mid_r, mid_c = row + dr*step, col + dc*step
                    land_start_r, land_start_c = row + dr*(step+1), col + dc*(step+1)
                    if not self.in_bounds(mid_r, mid_c) or not self.in_bounds(land_start_r, land_start_c):
                        break
                    mid_piece = board[mid_r][mid_c]
                    if mid_piece is None:
                        step += 1
                        continue
                    if mid_piece['player'] == piece['player']:
                        break
                    if (mid_r, mid_c) in visited_captures:
                        break
                    land_step = step + 1
                    while True:
                        land_r, land_c = row + dr*land_step, col + dc*land_step
                        if not self.in_bounds(land_r, land_c):
                            break
                        if board[land_r][land_c] is not None:
                            break
                        new_visited = set(visited_captures)
                        new_visited.add((mid_r, mid_c))
                        further = self.get_jumps(piece, land_r, land_c, new_visited)
                        if further:
                            for seq in further:
                                jumps.append([(land_r, land_c, mid_r, mid_c)] + seq)
                        else:
                            jumps.append([(land_r, land_c, mid_r, mid_c)])
                        land_step += 1
                    break
        return jumps

    def get_longest_jumps(self, player):
        board = self.board
        max_count = 0
        moves = {}
        for r in range(8):
            for c in range(8):
                piece = board[r][c]
                if piece and piece['player'] == player:
                    jumps = self.get_jumps(piece, r, c)
                    if jumps:
                        best_len = max(len(j) for j in jumps)
                        if best_len > 0:
                            moves[(r, c)] = [j for j in jumps if len(j) == best_len]
                            if best_len > max_count:
                                max_count = best_len
        moves = {k: v for k, v in moves.items() if len(v[0]) == max_count} if max_count > 0 else moves
        return max_count, moves

    def execute_single_jump_step(self, from_r, from_c, landing, captured):
        board = self.board
        piece = board[from_r][from_c]
        if piece is None:
            return None
        lr, lc = landing
        mr, mc = captured
        board[mr][mc] = None
        board[from_r][from_c] = None
        board[lr][lc] = piece
        return (lr, lc)

    def compute_highlights_for_selected(self):
        hl = []
        if not self.selected:
            return hl
        sr, sc = self.selected
        piece = self.board[sr][sc]
        if piece is None:
            return hl
        max_jump, all_moves = self.get_longest_jumps(self.turn)
        if max_jump > 0:
            if (sr, sc) in all_moves:
                for seq in all_moves[(sr, sc)]:
                    lr, lc, _, _ = seq[0]
                    if (lr, lc) not in hl:
                        hl.append((lr, lc))
                return hl
            else:
                return []
        # لا يوجد أكل: حركات عادية
        if piece['king']:
            dirs = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
            for dr, dc in dirs:
                step = 1
                while True:
                    nr, nc = sr + dr*step, sc + dc*step
                    if not self.in_bounds(nr, nc):
                        break
                    if self.board[nr][nc] is None:
                        hl.append((nr, nc))
                    else:
                        break
                    step += 1
        else:
            steps = [(1, -1), (1, 1)] if piece['player'] == 1 else [(-1, -1), (-1, 1)]
            for dr, dc in steps:
                nr, nc = sr + dr, sc + dc
                if self.in_bounds(nr, nc) and self.board[nr][nc] is None:
                    hl.append((nr, nc))
        return hl

    # ======= أحداث اللمس =======
    def on_touch_up(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_up(touch)

        r, c, piece_clicked = self._piece_at_pixel(touch.pos)
        max_jump, all_moves = self.get_longest_jumps(self.turn)

        if self.selected is None:
            if piece_clicked and piece_clicked['player'] == self.turn:
                if max_jump > 0:
                    if (r, c) in all_moves:
                        self.selected = (r, c)
                        self.pending_sequences = [[step for step in seq] for seq in all_moves[(r, c)]]
                        self.highlights = self.compute_highlights_for_selected()
                    else:
                        self.selected = None
                        self.pending_sequences = None
                        self.highlights = []
                else:
                    self.selected = (r, c)
                    self.pending_sequences = None
                    self.highlights = self.compute_highlights_for_selected()
        else:
            sr, sc = self.selected
            piece_now = self.board[sr][sc]
            if self.pending_sequences and len(self.pending_sequences) > 0:
                if (r, c) in self.highlights:
                    filtered = [seq for seq in self.pending_sequences if (seq[0][0], seq[0][1]) == (r, c)]
                    land_r, land_c, cap_r, cap_c = filtered[0][0]
                    self.execute_single_jump_step(sr, sc, (land_r, land_c), (cap_r, cap_c))
                    new_pending = []
                    for seq in filtered:
                        if len(seq) > 1:
                            new_pending.append(seq[1:])
                    if new_pending:
                        self.selected = (land_r, land_c)
                        self.pending_sequences = new_pending
                        self.highlights = self.compute_highlights_for_selected()
                    else:
                        piece_after = self.board[land_r][land_c]
                        if piece_after and piece_after['player'] == 1 and land_r == 7:
                            piece_after['king'] = True
                        if piece_after and piece_after['player'] == 2 and land_r == 0:
                            piece_after['king'] = True
                        self.selected = None
                        self.pending_sequences = None
                        self.highlights = []
                        self.turn = 2 if self.turn == 1 else 1
                else:
                    self.selected = None
                    self.pending_sequences = None
                    self.highlights = []
            else:
                if piece_now and (r, c) in self.highlights:
                    dx, dy = c - sc, r - sr
                    if piece_now['king']:
                        step_x = 1 if dx > 0 else -1
                        step_y = 1 if dy > 0 else -1
                        rr, cc = sr + step_y, sc + step_x
                        blocked = False
                        while (rr, cc) != (r, c):
                            if self.board[rr][cc] is not None:
                                blocked = True
                                break
                            rr += step_y
                            cc += step_x
                        if not blocked:
                            self.board[r][c] = piece_now
                            self.board[sr][sc] = None
                            if piece_now['player'] == 1 and r == 7:
                                piece_now['king'] = True
                            if piece_now['player'] == 2 and r == 0:
                                piece_now['king'] = True
                            self.turn = 2 if self.turn == 1 else 1
                        self.selected = None
                        self.highlights = []
                    else:
                        if piece_now['player'] == 1 and dy == 1 and abs(dx) == 1:
                            self.board[r][c] = piece_now
                            self.board[sr][sc] = None
                            if r == 7:
                                piece_now['king'] = True
                            self.turn = 2 if self.turn == 1 else 1
                        elif piece_now['player'] == 2 and dy == -1 and abs(dx) == 1:
                            self.board[r][c] = piece_now
                            self.board[sr][sc] = None
                            if r == 0:
                                piece_now['king'] = True
                            self.turn = 2 if self.turn == 1 else 1
                        self.selected = None
                        self.highlights = []
                else:
                    if piece_clicked and piece_clicked['player'] == self.turn:
                        self.selected = (r, c)
                        max_jump, all_moves = self.get_longest_jumps(self.turn)
                        if max_jump > 0 and (r, c) in all_moves:
                            self.pending_sequences = [[step for step in seq] for seq in all_moves[(r, c)]]
                        else:
                            self.pending_sequences = None
                        self.highlights = self.compute_highlights_for_selected()
                    else:
                        self.selected = None
                        self.pending_sequences = None
                        self.highlights = []

        self._trigger_redraw()
        return True

    def _piece_at_pixel(self, pos):
        # عكس الإسقاط على y: نقرأ من الأسفل ثم نقلب للمنطق (الصف 0 فوق)
        x, y = pos
        square_x, square_y, _, cell_size, _ = self._metrics()
        col = int((x - square_x) // cell_size)
        row_draw = int((y - square_y) // cell_size)
        if 0 <= col < 8 and 0 <= row_draw < 8:
            row = 7 - row_draw
            return row, col, self.board[row][col]
        return -1, -1, None

    # ======= الرسم =======
    def _trigger_redraw(self, *args):
        self.canvas.clear()
        with self.canvas:
            self._draw_background_wood()
            self._draw_board()
            self._draw_highlights()
            self._draw_pieces()

    def _draw_background_wood(self):
        W, H = self.width, self.height
        base = (139, 92, 51)
        random.seed(7)
        stripes = max(6, int(H // 6))
        for i in range(stripes):
            y0 = self.y + i * (H / stripes)
            y1 = self.y + (i + 1) * (H / stripes)
            wave = math.sin((i / max(1, stripes)) * 26.0) * 22
            n = (random.uniform(-1, 1) * 18)
            r = clamp(base[0] + wave * 0.6 + n * 0.8) / 255.0
            g = clamp(base[1] + wave * 0.4 + n * 0.5) / 255.0
            b = clamp(base[2] + wave * 0.2 + n * 0.3) / 255.0
            Color(r, g, b, 1)
            Rectangle(pos=(self.x, y0), size=(W, y1 - y0))

    def _draw_board(self):
        square_x, square_y, _, cell_size, _ = self._metrics()
        light = (240/255.0, 217/255.0, 181/255.0)
        dark  = (181/255.0, 136/255.0,  99/255.0)
        for row in range(8):
            for col in range(8):
                # نفس ألوان pygame: (row+col)%2==0 داكن — مع قلب y في موضع الرسم
                c = dark if (row + col) % 2 == 0 else light
                Color(*c, 1)
                Rectangle(
                    pos=(square_x + col * cell_size,
                         square_y + (7 - row) * cell_size),
                    size=(cell_size, cell_size)
                )
        Color(0, 0, 0, 1)
        Line(rectangle=(square_x, square_y, cell_size * 8, cell_size * 8), width=2)

    def _draw_highlights(self):
        square_x, square_y, _, cell_size, _ = self._metrics()
        Color(0, 0.8, 0, 0.6)
        for (hr, hc) in self.compute_highlights_for_selected():
            cx = square_x + hc * cell_size + cell_size / 2
            cy = square_y + (7 - hr) * cell_size + cell_size / 2
            Ellipse(pos=(cx - cell_size/6, cy - cell_size/6), size=(cell_size/3, cell_size/3))

    def _draw_pieces(self):
        _, _, _, _, radius = self._metrics()
        for row in range(8):
            for col in range(8):
                piece = self.board[row][col]
                if piece:
                    self._draw_single_piece(row, col, radius, piece)

    def _draw_single_piece(self, row, col, radius, piece):
        x, y = self.get_cell_center(col, row)
        # ظل
        Color(0, 0, 0, 0.4)
        Ellipse(pos=(x - radius + 3, y - radius - 3), size=(radius * 2, radius * 2))
        # جسم القطعة
        if piece['player'] == 1:
            Color(200/255.0, 0, 0, 1)
        else:
            Color(0, 0, 200/255.0, 1)
        Ellipse(pos=(x - radius, y - radius), size=(radius * 2, radius * 2))
        # حدّ أسود
        Color(0, 0, 0, 1)
        Line(circle=(x, y, radius), width=2)

        # تحديد القطعة المختارة
        if self.selected == (row, col):
            Color(1, 1, 0, 1)
            Line(circle=(x, y, radius + 5), width=2)

        # تاج الملك
        if piece.get('king'):
            Color(1, 215/255.0, 0, 1)
            Line(circle=(x, y, radius * 0.5), width=2)
            crown_w = radius * 0.9
            crown_h = radius * 0.6
            pts = [
                (x - crown_w * 0.5, y + crown_h * 0.05),
                (x - crown_w * 0.3, y + crown_h * 0.35),
                (x,                 y + crown_h * 0.15),
                (x + crown_w * 0.3, y + crown_h * 0.35),
                (x + crown_w * 0.5, y + crown_h * 0.05),
            ]
            Line(points=[p for xy in pts for p in xy], width=2, close=True)

class CheckersApp(App):
    title = "رقعة داما"

    def build(self):
        try:
            Window.maximize()
        except Exception:
            pass
        root = BoardWidget()
        Clock.schedule_once(lambda *_: root._trigger_redraw(), 0)
        return root

if __name__ == "__main__":
    CheckersApp().run()