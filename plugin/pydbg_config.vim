" ===========================================================================
" pydbg_config.vim — constants only.
"
" This file holds every tunable value. It loads before pydebugger.vim
" (alphabetical order of plugin files), so the logic file can rely on these
" globals. Override any of them in your init.vim BEFORE the plugin loads.
" ===========================================================================

if exists('g:loaded_pydbg_config')
  finish
endif
let g:loaded_pydbg_config = 1

" --- Connection (keep in sync with .env.example) ---------------------------
let g:pydebugger_host = get(g:, 'pydebugger_host', '127.0.0.1')
let g:pydebugger_port = get(g:, 'pydebugger_port', 5678)

" --- Engine location -------------------------------------------------------
" Repo root = parent of this file's directory (plugin/).
let s:root = expand('<sfile>:p:h:h')
" Python that runs the engine. Prefer the project venv, fall back to python3.
let s:venv_python = s:root . '/.venv/bin/python'
let g:pydebugger_python = get(g:, 'pydebugger_python',
      \ executable(s:venv_python) ? s:venv_python : 'python3')
" The engine entry point.
let g:pydebugger_main = get(g:, 'pydebugger_main', s:root . '/main.py')

" --- Colours ---------------------------------------------------------------
" Current line: light-blue background, black text stays readable.
highlight default PyDbgCurrentLine ctermbg=153 guibg=#add8e6 ctermfg=16 guifg=#000000
" Breakpoint dot: red.
highlight default PyDbgBreakSign ctermfg=red guifg=#ff5555

" --- Signs -----------------------------------------------------------------
" Current line is marked ONLY by the line highlight (no glyph in the gutter).
sign define PyDbgCurrent linehl=PyDbgCurrentLine
" Breakpoint is a red dot in the sign column.
sign define PyDbgBreak text=● texthl=PyDbgBreakSign
