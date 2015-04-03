set nocompatible              " be iMproved, required
filetype off                  " required

" set the runtime path to include Vundle and initialize
set rtp+=~/.vim/bundle/Vundle.vim
call vundle#begin()
" alternatively, pass a path where Vundle should install plugins
"call vundle#begin('~/some/path/here')

" let Vundle manage Vundle, required
Plugin 'gmarik/Vundle.vim'
Plugin 'bling/vim-airline'
Plugin 'kien/ctrlp.vim'
Plugin 'majutsushi/tagbar'
Plugin 'airblade/vim-gitgutter'
Plugin 'mhinz/vim-signify'
Plugin 'flazz/vim-colorschemes'
Plugin 'scrooloose/nerdtree'
Plugin 'groenewege/vim-less'
Plugin 'godlygeek/tabular'
Plugin 'plasticboy/vim-markdown'

" The following are examples of different formats supported.
" Keep Plugin commands between vundle#begin/end.
" plugin on GitHub repo
" Plugin 'tpope/vim-fugitive'
" " plugin from http://vim-scripts.org/vim/scripts.html
" Plugin 'L9'
" " Git plugin not hosted on GitHub
" Plugin 'git://git.wincent.com/command-t.git'
" " git repos on your local machine (i.e. when working on your own plugin)
" Plugin 'file:///home/gmarik/path/to/plugin'
" " The sparkup vim script is in a subdirectory of this repo called vim.
" " Pass the path to set the runtimepath properly.
" Plugin 'rstacruz/sparkup', {'rtp': 'vim/'}
" " Avoid a name conflict with L9
" Plugin 'user/L9', {'name': 'newL9'}

" All of your Plugins must be added before the following line
call vundle#end()            " required
filetype plugin indent on    " required
" To ignore plugin indent changes, instead use:
"filetype plugin on
"
" Brief help
" :PluginList       - lists configured plugins
" :PluginInstall    - installs plugins; append `!` to update or just :PluginUpdate
" :PluginSearch foo - searches for foo; append `!` to refresh local cache
" :PluginClean      - confirms removal of unused plugins; append `!` to auto-approve removal
"
" see :h vundle for more details or wiki for FAQ
" Put your non-Plugin stuff after this line

" Tab/Indent stuff
set smartindent        " automatically insert one extra level of indentation
set tabstop=4          " tab spacing
set softtabstop=4
set shiftwidth=4       " indent/outdent by 4 columns
set expandtab          " use spaces instead of tabs
set smarttab           " use tabs at the start of a line, spaces elsewhere
set number             " enable line numbers
set laststatus=2       " always show vim airline
" Smarter tab line
let g:airline#extensions#tabline#enabled = 1

" Persistent undo
" tell it to use an undo file
set undofile
" set a directory to store the undo history
set undodir=~/.vimundo/

" Enable syntax color highlighting
syntax on

" Set 256 color mode 
set t_Co=256
if v:version >= 700
  try
    " Colorscheme is inside a plugin
    colorscheme Tomorrow-Night

    " Open NERDTree if we open vim without any file loaded
    autocmd StdinReadPre * let s:std_in=1
    autocmd VimEnter * if argc() == 0 && !exists("s:std_in") | NERDTree | endif
    " Set Ctrl+n to toggle NERDTree
    map <C-n> :NERDTreeToggle<CR>
    " Disable markdown folding
    let g:vim_markdown_folding_disabled=1
  catch
  endtry
endif

