" ===========================================================================
" pydebugger.vim — logic and key maps.
"
" Loads after pydbg_config.vim and uses the constants defined there. Talks to
" the Python engine over a TCP socket with newline-delimited JSON.
" ===========================================================================

if exists('g:loaded_pydebugger')
  finish
endif
let g:loaded_pydebugger = 1

" --- state -----------------------------------------------------------------
let s:chan = -1          " socket channel id, -1 = not connected
let s:job = -1           " daemon job id (only when WE started it)
let s:owns_daemon = 0    " 1 = we spawned the daemon -> kill it on teardown
let s:was_connected = 0  " 1 once this session's socket connected
let s:buf = ''           " receive buffer for partial NDJSON lines
let s:cur_sign_id = 9001 " fixed id for the current-line sign
let s:eval_lines = []    " formatted eval results for the current stop
let s:show_bytecode = 0  " 1 = show the dis bytecode panel
let s:profiling = 0 " 1 = show profiling panel

" One-line key hint shown on the 'connected' message.
let s:keys_hint = 'F3 bytecode  F4 eval  F5 run  F6 over  F7 into  F8 out  F9 break  F10 connect  F11 profiling F12 stop'

" ===========================================================================
" Connection: reuse a running daemon, otherwise spawn one for THIS file.
" ===========================================================================
function! s:Connect() abort
  if s:chan > 0
    echo '[pydbg] already connected'
    return
  endif
  " 1) A daemon already listens -> reuse it.
  if s:TryConnect()
    echo s:keys_hint
    return
  endif
  " 2) Port free -> spawn a daemon that debugs the current file.
  call s:StartDaemon(expand('%:p'))
endfunction

" Try one TCP connect. sockconnect() throws on a free port, so catch it.
function! s:TryConnect() abort
  let l:addr = g:pydebugger_host . ':' . g:pydebugger_port
  let l:chan = 0
  try
    let l:chan = sockconnect('tcp', l:addr, {'on_data': function('s:OnData')})
  catch
    let l:chan = 0
  endtry
  if l:chan > 0
    let s:chan = l:chan
    let s:was_connected = 1
    call s:FlushBreaks()
    return 1
  endif
  return 0
endfunction

" Spawn the engine: python main.py <target file>.
function! s:StartDaemon(target) abort
  let l:cmd = [g:pydebugger_python, g:pydebugger_main, a:target]
  let s:job = jobstart(l:cmd, {
        \ 'on_stderr': function('s:OnDaemonErr'),
        \ 'on_exit':   function('s:OnDaemonExit'),
        \ })
  if s:job <= 0
    echohl ErrorMsg | echo '[pydbg] cannot start daemon' | echohl None
    let s:job = -1
    return
  endif
  let s:owns_daemon = 1
  let s:was_connected = 0
  echo '[pydbg] starting daemon for ' . fnamemodify(a:target, ':t') . ' ...'
  " The daemon needs time to bind the port. Retry connect for ~3s.
  call timer_start(150, function('s:RetryConnect'), {'repeat': 20})
endfunction

function! s:RetryConnect(timer) abort
  if s:chan > 0
    call timer_stop(a:timer)
    return
  endif
  if s:TryConnect()
    call timer_stop(a:timer)
    echo s:keys_hint
  endif
endfunction

function! s:OnDaemonErr(job, data, event) abort
  for l:line in a:data
    if l:line =~# '\S'
      echom '[pydbg daemon] ' . l:line
    endif
  endfor
endfunction

function! s:OnDaemonExit(job, code, event) abort
  let s:job = -1
  let s:owns_daemon = 0
  " The engine quit before we ever connected -> report it (e.g. bad file).
  if !s:was_connected
    echohl ErrorMsg
    echo '[pydbg] engine exited before connecting (see :messages)'
    echohl None
  endif
endfunction

" ===========================================================================
" Receive: split the NDJSON stream into messages.
" ===========================================================================
function! s:OnData(chan, data, name) abort
  let s:buf .= join(a:data, "\n")
  while 1
    let l:nl = stridx(s:buf, "\n")
    if l:nl < 0
      break
    endif
    let l:line = strpart(s:buf, 0, l:nl)
    let s:buf = strpart(s:buf, l:nl + 1)
    if l:line =~# '\S'
      call s:Handle(json_decode(l:line))
    endif
  endwhile
endfunction

" ===========================================================================
" Handle events coming FROM the engine.
" ===========================================================================
function! s:Handle(msg) abort
  let l:ev = get(a:msg, 'event', '')
  if l:ev ==# 'stopped'
    call s:ShowStop(a:msg)
  elseif l:ev ==# 'variables'
    call s:RenderVars(a:msg)
  elseif l:ev ==# 'evaluation'
    call s:ShowEval(a:msg)
  elseif l:ev ==# 'bytecode'
    call s:RenderBytecode(a:msg)
  elseif l:ev ==# 'output'
    echom '[pydbg] ' . get(a:msg, 'text', '')
  elseif l:ev ==# 'terminated'
    call s:Teardown()
    echo '[pydbg] program finished (press F10 to run again)'
  elseif l:ev ==# 'profiler'
    call s:ShowProfiler(a:msg)
  endif
endfunction

" Jump to file:line. If the file is shown in a tab, switch to it; otherwise
" open it in a NEW tab. Mark the current line by background highlight only.
function! s:ShowStop(msg) abort
  let l:file = get(a:msg, 'file', '')
  let l:line = get(a:msg, 'line', 0)
  if empty(l:file) || l:line <= 0
    return
  endif
  let s:eval_lines = []
  let l:abs = fnamemodify(l:file, ':p')
  if fnamemodify(bufname('%'), ':p') !=# l:abs
    let l:bnr = bufnr(l:abs)
    let l:wins = l:bnr > 0 ? win_findbuf(l:bnr) : []
    if !empty(l:wins)
      call win_gotoid(l:wins[0])
    else
      execute 'tabedit ' . fnameescape(l:file)
    endif
  endif
  call cursor(l:line, 1)
  normal! zz
  call s:ClearCurrent()
  execute printf('sign place %d line=%d name=PyDbgCurrent file=%s',
        \ s:cur_sign_id, l:line, l:abs)
  " Refresh the variables panel for this stop.
  call s:Send({'cmd': 'variables'})
  if s:show_bytecode
    call s:Send({'cmd': 'disassemble'})
  endif
endfunction

function! s:ClearCurrent() abort
  silent! execute 'sign unplace ' . s:cur_sign_id
endfunction

" ===========================================================================
" Variables panel: a foldable tree. Locals and Globals are top-level folds;
" user-class instances expand their attributes one level deeper.
" ===========================================================================
function! s:RenderDescriptor(name, desc, indent, lines) abort
  let l:pad = repeat(' ', a:indent * 2)
  call add(a:lines, printf('%s%s = %s (%s)',
        \ l:pad, a:name, get(a:desc, 'value', ''), get(a:desc, 'type', '')))
  if has_key(a:desc, 'attributes')
    for [l:k, l:v] in items(a:desc.attributes)
      call s:RenderDescriptor(l:k, l:v, a:indent + 1, a:lines)
    endfor
  endif
endfunction

function! s:RenderVars(msg) abort
  let l:lines = ['Locals']
  for [l:k, l:v] in items(get(a:msg, 'locals', {}))
    call s:RenderDescriptor(l:k, l:v, 1, l:lines)
  endfor
  call add(l:lines, 'Globals')
  for [l:k, l:v] in items(get(a:msg, 'globals', {}))
    call s:RenderDescriptor(l:k, l:v, 1, l:lines)
  endfor
  if !empty(s:eval_lines)
    call add(l:lines, 'Eval')
    call extend(l:lines, s:eval_lines)
  endif

  let l:winid = bufwinid('__PyDbgVars__')
  if l:winid == -1
    botright 12split __PyDbgVars__
    setlocal buftype=nofile bufhidden=hide noswapfile nobuflisted
    setlocal nonumber norelativenumber nowrap
    " Folding by indent: 'Locals'/'Globals' fold their children; an instance
    " folds its attributes. Toggle a fold with <Tab> or za.
    " foldlevel=0: Locals/Globals start collapsed; open with <Tab> or za.
    setlocal foldmethod=indent shiftwidth=2 foldlevel=0
    nnoremap <buffer> <silent> <Tab> za
    " Always-visible key bar at the top of the panel (not part of the folds).
    let &l:winbar = 'F3 bc  F4 eval  F5 run  F6 over  F7 into  F8 out  F9 break  F11 profiling  F12 stop'
          \ . '  | <Tab> fold'
    let l:winid = win_getid()
    wincmd p
  endif
  let l:buf = winbufnr(l:winid)
  call setbufline(l:buf, 1, l:lines)
  call deletebufline(l:buf, len(l:lines) + 1, '$')
endfunction

function! s:CloseVars() abort
  let l:b = bufnr('__PyDbgVars__')
  if l:b <= 0
    return
  endif
  for l:w in win_findbuf(l:b)
    call nvim_win_close(l:w, 1)
  endfor
  if bufexists(l:b)
    execute 'bwipeout! ' . l:b
  endif
endfunction

" Render the dis listing in a right-side panel. The text already marks the
" current instruction with -->.
function! s:RenderBytecode(msg) abort
  if !s:show_bytecode
    return
  endif
  let l:lines = split(get(a:msg, 'text', ''), "\n", 1)
  let l:winid = bufwinid('__PyDbgBytecode__')
  if l:winid == -1
    botright vsplit __PyDbgBytecode__
    setlocal buftype=nofile bufhidden=hide noswapfile nobuflisted
    setlocal nonumber norelativenumber nowrap
    let &l:winbar = 'BYTECODE  (F3 toggles)  --> current instruction'
    let l:winid = win_getid()
    wincmd p
  endif
  let l:buf = winbufnr(l:winid)
  call setbufline(l:buf, 1, l:lines)
  call deletebufline(l:buf, len(l:lines) + 1, '$')
endfunction

function! s:ProfilerStart() abort
  if s:profiling
    echo '[pydbg] already profiling (report at next stop)'
    return
  endif
  let s:profiling = 1
  call s:CloseProfiler()
  call s:EnsureProfilerPanel()
  call s:SetProfilerLines(['Sampling with pyinstrument ...  (auto-stops at next stop)'])
  call s:Send({'cmd': 'profile_start'})
  echo '[pydbg] profiling started'
endfunction

function! s:ProfilerStop() abort
  let s:profiling = 0
  call s:Send({'cmd': 'profile_stop'})
endfunction

" F11: one-shot profile. Starts sampling, engine auto-resumes, report lands
" in the panel at the next breakpoint or program end.
function! s:ToggleProfiler() abort
  call s:ProfilerStart()
endfunction

function! s:ShowProfiler(msg) abort
  let s:profiling = 0
  call s:EnsureProfilerPanel()
  call s:SetProfilerLines(split(get(a:msg, 'text', ''), "\n", 1))
endfunction

function! s:CloseProfiler() abort
  let l:b = bufnr('__PyDbgProfiler__')
  if l:b <= 0
    return
  endif
  for l:w in win_findbuf(l:b)
    call nvim_win_close(l:w, 1)
  endfor
  if bufexists(l:b)
    execute 'bwipeout! ' . l:b
  endif
endfunction

function! s:CloseBytecode() abort
  let l:b = bufnr('__PyDbgBytecode__')
  if l:b <= 0
    return
  endif
  for l:w in win_findbuf(l:b)
    call nvim_win_close(l:w, 1)
  endfor
  if bufexists(l:b)
    execute 'bwipeout! ' . l:b
  endif
endfunction

" F3: toggle the bytecode panel. When turning on during a stop, fetch it now.
function! s:ToggleBytecode() abort
  let s:show_bytecode = !s:show_bytecode
  if s:show_bytecode
    echo '[pydbg] bytecode ON'
    if s:chan > 0
      call s:Send({'cmd': 'disassemble'})
    endif
  else
    call s:CloseBytecode()
    echo '[pydbg] bytecode OFF'
  endif
endfunction

" ===========================================================================
" Teardown: close socket, kill our daemon, drop sign and panel.
" Used by F12 and by the 'terminated' event.
" ===========================================================================
function! s:Teardown() abort
  if s:chan > 0
    call chanclose(s:chan)
  endif
  let s:chan = -1
  if s:owns_daemon && s:job > 0
    call jobstop(s:job)
  endif
  let s:job = -1
  let s:owns_daemon = 0
  let s:buf = ''
  call s:ClearCurrent()
  call s:CloseVars()
  call s:CloseBytecode()
  let s:profiling = 0
endfunction

function! s:Disconnect() abort
  call s:Teardown()
  echo '[pydbg] disconnected'
endfunction

" ===========================================================================
" Commands sent TO the engine.
" ===========================================================================
" Send a flow command. Never auto-connects: only F10 starts a session.
function! s:Send(obj) abort
  if s:chan <= 0
    echohl WarningMsg | echo '[pydbg] not running — press F10 to start' | echohl None
    return
  endif
  call chansend(s:chan, json_encode(a:obj) . "\n")
endfunction

" Low-level send with no 'not running' warning (for internal use).
function! s:SendRaw(obj) abort
  if s:chan > 0
    call chansend(s:chan, json_encode(a:obj) . "\n")
  endif
endfunction

" Re-arm every placed breakpoint in the freshly connected engine.
function! s:FlushBreaks() abort
  for l:entry in sign_getplaced()
    let l:file = fnamemodify(bufname(l:entry.bufnr), ':p')
    for l:sign in l:entry.signs
      if l:sign.name ==# 'PyDbgBreak'
        call s:SendRaw({'cmd': 'set_breakpoint', 'file': l:file, 'line': l:sign.lnum})
      endif
    endfor
  endfor
endfunction

function! s:Continue() abort
  call s:Send({'cmd': 'continue'})
endfunction

function! s:EnsureProfilerPanel() abort
  if bufwinid('__PyDbgProfiler__') != -1
    return
  endif
  botright vsplit __PyDbgProfiler__
  setlocal buftype=nofile bufhidden=hide noswapfile nobuflisted
  setlocal nonumber norelativenumber nowrap
  let &l:winbar = 'PROFILER (pyinstrument)  F11 to toggle'
  wincmd p
endfunction

function! s:SetProfilerLines(lines) abort
  let l:winid = bufwinid('__PyDbgProfiler__')
  if l:winid == -1
    return
  endif
  let l:buf = winbufnr(l:winid)
  call setbufline(l:buf, 1, a:lines)
  call deletebufline(l:buf, len(a:lines) + 1, '$')
endfunction

function! s:ShowProfiler(msg) abort
  call s:EnsureProfilerPanel()
  call s:SetProfilerLines(split(get(a:msg, 'text', ''), "\n", 1))
endfunction

function! s:StepOver() abort
  call s:Send({'cmd': 'step_over'})
endfunction

function! s:StepInto() abort
  call s:Send({'cmd': 'step_into'})
endfunction

function! s:StepOut() abort
  call s:Send({'cmd': 'step_out'})
endfunction

" Toggle a breakpoint on the current line, reflecting it with a red dot.
function! s:ToggleBreak() abort
  let l:file = fnamemodify(bufname('%'), ':p')
  let l:line = line('.')
  let l:sid = 7000 + l:line
  if sign_getplaced(l:file, {'group': '', 'id': l:sid})[0].signs != []
    execute 'sign unplace ' . l:sid . ' file=' . l:file
    call s:SendRaw({'cmd': 'clear_breakpoint', 'file': l:file, 'line': l:line})
  else
    execute printf('sign place %d line=%d name=PyDbgBreak file=%s',
          \ l:sid, l:line, l:file)
    call s:SendRaw({'cmd': 'set_breakpoint', 'file': l:file, 'line': l:line})
  endif
endfunction

" Append one evaluation result to the Eval section of the panel.
function! s:ShowEval(msg) abort
  if has_key(a:msg, 'error')
    let l:line = printf('  %s -> %s', a:msg.expr, a:msg.error)
  else
    let l:line = printf('  %s = %s (%s)', a:msg.expr, a:msg.value, a:msg.type)
  endif
  call add(s:eval_lines, l:line)
  let l:b = bufnr('__PyDbgVars__')
  if l:b <= 0
    return
  endif
  if len(s:eval_lines) == 1
    call appendbufline(l:b, '$', 'Eval')
  endif
  call appendbufline(l:b, '$', l:line)
endfunction

" Send an expression to evaluate in the current frame.
function! s:SendEval(expr) abort
  if a:expr =~# '\S'
    call s:Send({'cmd': 'evaluate', 'expr': a:expr})
  endif
endfunction

" Prompt for an expression, then evaluate it.
function! s:EvalPrompt() abort
  call s:SendEval(input('pydbg eval> '))
endfunction

function! s:Help() abort
  echo join([
        \ 'F3  bytecode    F4  eval        F5  continue',
        \ 'F6  step over   F7  step into   F8  step out',
        \ 'F9  breakpoint  F10 connect     F11 profiling',
        \ 'F12 stop',
        \ 'In the variables panel: <Tab> or za toggles a fold.',
        \ ], "\n")
endfunction

" ===========================================================================
" User commands and key maps.
" ===========================================================================
command! PyDbgConnect     call s:Connect()
command! PyDbgDisconnect  call s:Disconnect()
command! PyDbgContinue    call s:Continue()
command! PyDbgStepOver    call s:StepOver()
command! PyDbgStepInto    call s:StepInto()
command! PyDbgStepOut     call s:StepOut()
command! PyDbgToggleBreak call s:ToggleBreak()
command! PyDbgBytecode    call s:ToggleBytecode()
command! -nargs=+ PyDbgEval call s:SendEval(<q-args>)
command! PyDbgHelp        call s:Help()
command! PyDbgProfiler call s:ToggleProfiler()

nnoremap <silent> <F5>  :PyDbgContinue<CR>
nnoremap <silent> <F6>  :PyDbgStepOver<CR>
nnoremap <silent> <F7>  :PyDbgStepInto<CR>
nnoremap <silent> <F8>  :PyDbgStepOut<CR>
nnoremap <silent> <F9>  :PyDbgToggleBreak<CR>
nnoremap <silent> <F3>  :PyDbgBytecode<CR>
nnoremap <silent> <F4>  :call <SID>EvalPrompt()<CR>
nnoremap <silent> <F10> :PyDbgConnect<CR>
nnoremap <silent> <F11> :PyDbgProfiler<CR>
nnoremap <silent> <F12> :PyDbgDisconnect<CR>
