// Tecla's pixel art: every frame as a character map, one letter per pixel,
// `.` transparent. Two sizes: `full`, 30 x 24 px (12 terminal rows, each
// cell two stacked pixels), and `mini`, 20 x 16 px (8 rows) for short or
// narrow terminals. A frame is either whole (`rows`) or another frame with
// some rows replaced (`from` + `patch`, keyed by row index, each row whole).
// `poses` are the animations: [frame, ms] steps, looped, for each mood.
//
// What's between `ART =` and `as const` is strict JSON (no comments, no
// trailing commas): tools/preview.py reads it straight from this file, so
// the preview always draws what the mod draws.
//
// Palette:
//   H  hair, chestnut
//   h  hair highlight
//   S  skin
//   s  skin shade
//   W  eye shine
//   E  eye dark, lashes
//   e  iris, violet
//   B  blush
//   M  mouth
//   V  cardigan, lavender
//   v  cardigan shade
//   C  blouse, cream
//   Q  skirt, plum
//   q  skirt pleat
//   K  book cover, red
//   k  pages
//   l  page lines
//   O  shoes
//   G  glasses and magnifier frame
//   w  lens
//   P  star hair clip
//   Y  sparkle, bookmark
//   z  sleepy z
//   T  wood: stamp and magnifier handles
//   R  open mouth, stamp rubber
//   i  stamp ink
//   x  thud lines
//   A  question mark
//   X  exclamation mark

export const ART = {
  "palette": {
    "H": "#78482e",
    "h": "#b0704a",
    "S": "#fadece",
    "s": "#ecc0ac",
    "W": "#ffffff",
    "E": "#3a285c",
    "e": "#9676e1",
    "B": "#f8a6b4",
    "M": "#de7080",
    "V": "#c4ace8",
    "v": "#a88ed2",
    "C": "#faf4e8",
    "Q": "#783a60",
    "q": "#602c4c",
    "K": "#b23e4a",
    "k": "#f6eed8",
    "l": "#c8bca2",
    "O": "#5c342c",
    "G": "#c4965c",
    "w": "#cde4f6",
    "P": "#ff8cba",
    "Y": "#fad264",
    "z": "#a0b4e6",
    "T": "#96683e",
    "R": "#602430",
    "i": "#d6405a",
    "x": "#ececf4",
    "A": "#f0a030",
    "X": "#ff6060"
  },
  "full": {
    "idle": {
      "rows": [
        "..............HH..............",
        ".........HHHHHHHHHHHH.........",
        ".......HHHHhhHHHHHHHHHH.......",
        "......HHHGwGGwGHHHHHHHHH......",
        ".....HHHHHHHHHHHHHHPPHHHH.....",
        ".....HHHHHSSHHHHHHHHPSHHHH....",
        ".....HHSSSSSSSSSSSSSSSSHH.....",
        ".....HHSSEEESSSSSSEEESSHH.....",
        ".....HHSSWeESSSSSSWeESSHH.....",
        ".....HHSSeeeSSSSSSeeeSSHH.....",
        ".....HHSBEEEBSSSSBEEEBSHH.....",
        ".....HHSSBBSSSMMSSSBBSSHH.....",
        "......HHSSSSSSSSSSSSSSHH......",
        "......HHHsSSSSSSSSSSsHHH......",
        ".....HHHVVVVCSSSSCVVVVHHH.....",
        ".....HHHVVVVVCCCCVVVVVHHH.....",
        ".....HHHvVVVVVCCVVVVVvHHH.....",
        ".....HHSVKKKKKKKKKKKKVSHH.....",
        ".....HHSVKKKKKYYKKKKKVSHH.....",
        "......HHVKKKKKKKKKKKKVHH......",
        "........QQQQQQQQQQQQQQ........",
        ".......QQQqQQQqqQQQqQQQ.......",
        "...........SS....SS...........",
        "..........OOO....OOO.........."
      ]
    },
    "idle-blink": {
      "from": "idle",
      "patch": {
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "9": ".....HHSSEEESSSSSSEEESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH....."
      }
    },
    "reading": {
      "from": "idle",
      "patch": {
        "17": ".....HHSkllllkKKkllllkSHH.....",
        "18": ".....HHSkkkkkkKKkkkkkkSHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "reading-blink": {
      "from": "idle",
      "patch": {
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "9": ".....HHSSEEESSSSSSEEESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "17": ".....HHSkllllkKKkllllkSHH.....",
        "18": ".....HHSkkkkkkKKkkkkkkSHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "reading-turn": {
      "from": "idle",
      "patch": {
        "17": ".....HHSkllllkKkkllllkSHH.....",
        "18": ".....HHSkkkkkkKkkkkkkkSHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "stamp-up": {
      "from": "idle",
      "patch": {
        "8": ".....HHSSWeESSSSSSWeESSHH.TT..",
        "9": ".....HHSSeeeSSSSSSeeeSSHH.TT..",
        "10": ".....HHSBEEEBSSSSBEEEBSHHTTTT.",
        "11": ".....HHSSBBSSSMMSSSBBSSHHRRRR.",
        "12": "......HHSSSSSSSSSSSSSSHH..SS..",
        "13": "......HHHsSSSSSSSSSSsHHH..V...",
        "14": ".....HHHVVVVCSSSSCVVVVHHH.V...",
        "15": ".....HHHVVVVVCCCCVVVVVHHHV....",
        "16": ".....HHHvVVVVVCCVVVVVvHHHv....",
        "17": ".....HHSkllllkKKkllllkHHH.....",
        "18": ".....HHSkkkkkkKKkkkkkkHHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "stamp-down": {
      "from": "idle",
      "patch": {
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSESSSSSSSSESSSHH.....",
        "9": ".....HHSSESESSSSSSESESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "12": "......HHSSSSSSSS..SS..HH......",
        "13": "......HHHsSSSSSS..TT..VH......",
        "14": ".....HHHVVVVCSSx.TTTT.xHHV....",
        "15": ".....HHHVVVVVCCC.RRRR.HHHV....",
        "16": ".....HHHvVVVVVxxVVVVVvxxHv....",
        "17": ".....HHSkllllkKKkllllkHHH.....",
        "18": ".....HHSkkkkkkKKkkkkkkHHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "stamp-mark": {
      "from": "idle",
      "patch": {
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSESSSSSSSSESSSHH.TT..",
        "9": ".....HHSSESESSSSSSESESSHH.TT..",
        "10": ".....HHSBSSSBSSSSBSSSBSHHTTTT.",
        "11": ".....HHSSBBSSSMMSSSBBSSHHRRRR.",
        "12": "......HHSSSSSSSSSSSSSSHH..SS..",
        "13": "......HHHsSSSSSSSSSSsHHH..V...",
        "14": ".....HHHVVVVCSSSSCVVVVHHH.V...",
        "15": ".....HHHVVVVVCCCCVVVVVHHHV....",
        "16": ".....HHHvVVVVVCCVVVVVvHHHv....",
        "17": ".....HHSkllllkKKkiiiikHHH.....",
        "18": ".....HHSkkkkkkKKkkiikkHHH.....",
        "19": "......HHKKKKKKKKKKKKKKHH......"
      }
    },
    "search": {
      "from": "idle",
      "patch": {
        "4": ".....HHHHHHHHHHHHHHPPHHHH.GGG.",
        "5": ".....HHHHHSSHHHHHHHHPSHHHGwwwG",
        "6": ".....HHSSSSSSSSSSSSSSSSHHGwWwG",
        "7": ".....HHSSEeESSSSSSEeESSHHGwwwG",
        "8": ".....HHSSeWeSSSSSSeWeSSHH.GGG.",
        "9": ".....HHSSEEESSSSSSEEESSHH.T...",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.T...",
        "11": ".....HHSSBBSSSMMSSSBBSSHH.SS..",
        "12": "......HHSSSSSSSSSSSSSSHH..V...",
        "13": "......HHHsSSSSSSSSSSsHHH..V...",
        "14": ".....HHHVVVVCSSSSCVVVVHHH.V...",
        "15": ".....HHHVVVVVCCCCVVVVVHHHV....",
        "16": ".....HHHvVVVVVCCVVVVVvHHHv....",
        "17": ".....HHSVKKKKKKKKKKKKVHHH.....",
        "18": ".....HHSVKKKKKYYKKKKKVHHH....."
      }
    },
    "search-2": {
      "from": "idle",
      "patch": {
        "3": "......HHHGwGGwGHHHHHHHHH..GGG.",
        "4": ".....HHHHHHHHHHHHHHPPHHHHGwwwG",
        "5": ".....HHHHHSSHHHHHHHHPSHHHGwWwG",
        "6": ".....HHSSSSSSSSSSSSSSSSHHGwwwG",
        "7": ".....HHSSEeESSSSSSEeESSHH.GGG.",
        "8": ".....HHSSeWeSSSSSSeWeSSHH.T...",
        "9": ".....HHSSEEESSSSSSEEESSHH.T...",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.SS..",
        "11": ".....HHSSBBSSSMMSSSBBSSHH.V...",
        "12": "......HHSSSSSSSSSSSSSSHH..V...",
        "13": "......HHHsSSSSSSSSSSsHHH..V...",
        "14": ".....HHHVVVVCSSSSCVVVVHHH.V...",
        "15": ".....HHHVVVVVCCCCVVVVVHHHV....",
        "16": ".....HHHvVVVVVCCVVVVVvHHHv....",
        "17": ".....HHSVKKKKKKKKKKKKVHHH.....",
        "18": ".....HHSVKKKKKYYKKKKKVHHH....."
      }
    },
    "puzzled": {
      "from": "idle",
      "patch": {
        "0": "..............HH...........AA.",
        "1": ".........HHHHHHHHHHHH.....A..A",
        "2": ".......HHHHhhHHHHHHHHHH.....A.",
        "3": "......HHHGwGGwGHHHHHHHHH...A..",
        "5": ".....HHHHHSSHHHHHHHHPSHHHH.A..",
        "8": ".....HHSSEWeSSSSSSEWeSSHH.....",
        "9": ".....HHSSEeeSSSSSSEeeSSHH.....",
        "11": ".....HHSSBBSSMSMSSSBBSSHH....."
      }
    },
    "puzzled-2": {
      "from": "idle",
      "patch": {
        "1": ".........HHHHHHHHHHHH......AA.",
        "2": ".......HHHHhhHHHHHHHHHH...A..A",
        "3": "......HHHGwGGwGHHHHHHHHH....A.",
        "4": ".....HHHHHHHHHHHHHHPPHHHH..A..",
        "6": ".....HHSSSSSSSSSSSSSSSSHH..A..",
        "8": ".....HHSSEWeSSSSSSEWeSSHH.....",
        "9": ".....HHSSEeeSSSSSSEeeSSHH.....",
        "11": ".....HHSSBBSSMSMSSSBBSSHH....."
      }
    },
    "happy": {
      "from": "idle",
      "patch": {
        "0": "......Y.......HH..............",
        "1": ".....Y.Y.HHHHHHHHHHHH.........",
        "2": "......YHHHHhhHHHHHHHHHH.......",
        "7": ".....HHSSSSSSSSSSSSSSSSHH...Y.",
        "8": ".....HHSSSESSSSSSSSESSSHH..Y.Y",
        "9": ".....HHSSESESSSSSSESESSHH...Y.",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "13": ".Y....HHHsSSSSSSSSSSsHHH......"
      }
    },
    "happy-2": {
      "from": "idle",
      "patch": {
        "0": "..............HH..........Y...",
        "1": ".........HHHHHHHHHHHH....Y.Y..",
        "2": ".......HHHHhhHHHHHHHHHH...Y...",
        "3": ".Y....HHHGwGGwGHHHHHHHHH......",
        "4": "Y.Y..HHHHHHHHHHHHHHPPHHHH.....",
        "5": ".Y...HHHHHSSHHHHHHHHPSHHHH....",
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSESSSSSSSSESSSHH.....",
        "9": ".....HHSSESESSSSSSESESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "14": ".....HHHVVVVCSSSSCVVVVHHH...Y."
      }
    },
    "sleepy": {
      "from": "idle",
      "patch": {
        "0": "..............HH.......zz.....",
        "1": ".........HHHHHHHHHHHH...z.....",
        "3": "......HHHGwGGwGHHHHHHHHH..zzz.",
        "4": ".....HHHHHHHHHHHHHHPPHHHH...z.",
        "5": ".....HHHHHSSHHHHHHHHPSHHHH.z..",
        "6": ".....HHSSSSSSSSSSSSSSSSHH.zzz.",
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "9": ".....HHSSEEESSSSSSEEESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "11": ".....HHSSBBSSSSMSSSBBSSHH....."
      }
    },
    "sleepy-2": {
      "from": "idle",
      "patch": {
        "1": ".........HHHHHHHHHHHH.....zzzz",
        "2": ".......HHHHhhHHHHHHHHHH.....z.",
        "3": "......HHHGwGGwGHHHHHHHHH...z..",
        "4": ".....HHHHHHHHHHHHHHPPHHHH.zzzz",
        "6": ".....HHSSSSSSSSSSSSSSSSHH.zz..",
        "7": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "8": ".....HHSSSSSSSSSSSSSSSSHH.....",
        "9": ".....HHSSEEESSSSSSEEESSHH.....",
        "10": ".....HHSBSSSBSSSSBSSSBSHH.....",
        "11": ".....HHSSBBSSSSMSSSBBSSHH....."
      }
    },
    "lookup": {
      "from": "idle",
      "patch": {
        "0": "..............HH...........XX.",
        "1": ".........HHHHHHHHHHHH......XX.",
        "2": ".......HHHHhhHHHHHHHHHH....XX.",
        "3": "......HHHGwGGwGHHHHHHHHH...XX.",
        "5": ".....HHHHHSSHHHHHHHHPSHHHH.XX.",
        "12": "......HHSSSSSSRRSSSSSSHH......"
      }
    },
    "lookup-2": {
      "from": "idle",
      "patch": {
        "1": ".........HHHHHHHHHHHH......XX.",
        "2": ".......HHHHhhHHHHHHHHHH....XX.",
        "3": "......HHHGwGGwGHHHHHHHHH...XX.",
        "4": ".....HHHHHHHHHHHHHHPPHHHH..XX.",
        "6": ".....HHSSSSSSSSSSSSSSSSHH..XX.",
        "12": "......HHSSSSSSRRSSSSSSHH......"
      }
    }
  },
  "mini": {
    "idle": {
      "rows": [
        "..........H.........",
        "......HHHHHHHH......",
        "....HHHhhHHHHHHH....",
        "...HHHGwGGwGHHPPH...",
        "...HHHHHHHHHHHHPHH..",
        "...HHSSSSSSSSSSHH...",
        "...HHSEESSSSEESHH...",
        "...HHSWeSSSSWeSHH...",
        "...HHBEESSSSEEBHH...",
        "...HHSSSSMMSSSSHH...",
        "....HHVVCSSCVVHH....",
        "...HHHVVVCCVVVHHH...",
        "...HHSVKKKKKKVSHH...",
        "....HHKKKYYKKKHH....",
        "......QQQqqQQQ......",
        ".......OO..OO......."
      ]
    },
    "idle-blink": {
      "from": "idle",
      "patch": {
        "6": "...HHSSSSSSSSSSHH...",
        "7": "...HHSSSSSSSSSSHH..."
      }
    },
    "reading": {
      "from": "idle",
      "patch": {
        "12": "...HHSkklKKlkkSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "reading-blink": {
      "from": "idle",
      "patch": {
        "6": "...HHSSSSSSSSSSHH...",
        "7": "...HHSSSSSSSSSSHH...",
        "12": "...HHSkklKKlkkSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "reading-turn": {
      "from": "idle",
      "patch": {
        "12": "...HHSkklkKlkkSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "stamp-up": {
      "from": "idle",
      "patch": {
        "6": "...HHSEESSSSEESHH.T.",
        "7": "...HHSWeSSSSWeSHHTTT",
        "8": "...HHBEESSSSEEBHHRRR",
        "9": "...HHSSSSMMSSSSHH.S.",
        "12": "...HHSkklKKlkkSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "stamp-down": {
      "from": "idle",
      "patch": {
        "7": "...HHESSESSESSEHH...",
        "8": "...HHBSSSSSSSSBHH...",
        "9": "...HHSSSSMM.S.SHH...",
        "10": "....HHVVCSS.T.HH....",
        "11": "...HHHVVVCxTTTxHH...",
        "12": "...HHSkklKKRRRSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "stamp-mark": {
      "from": "idle",
      "patch": {
        "6": "...HHSEESSSSEESHH.T.",
        "7": "...HHESSESSESSEHHTTT",
        "8": "...HHBSSSSSSSSBHHRRR",
        "9": "...HHSSSSMMSSSSHH.S.",
        "12": "...HHSkklKKiikSHH...",
        "13": "....HHKKKKKKKKHH...."
      }
    },
    "search": {
      "from": "idle",
      "patch": {
        "2": "....HHHhhHHHHHHH..G.",
        "3": "...HHHGwGGwGHHPPHGwG",
        "4": "...HHHHHHHHHHHHPH.G.",
        "5": "...HHSSSSSSSSSSHHT..",
        "6": "...HHSWeSSSSWeSHHS..",
        "7": "...HHSEESSSSEESHH...",
        "8": "...HHBSSSSSSSSBHH..."
      }
    },
    "search-2": {
      "from": "idle",
      "patch": {
        "1": "......HHHHHHHH....G.",
        "2": "....HHHhhHHHHHHH.GwG",
        "3": "...HHHGwGGwGHHPPH.G.",
        "4": "...HHHHHHHHHHHHPHT..",
        "5": "...HHSSSSSSSSSSHHS..",
        "6": "...HHSWeSSSSWeSHH...",
        "7": "...HHSEESSSSEESHH...",
        "8": "...HHBSSSSSSSSBHH..."
      }
    },
    "puzzled": {
      "from": "idle",
      "patch": {
        "0": "..........H......AA.",
        "1": "......HHHHHHHH.....A",
        "2": "....HHHhhHHHHHHH..A.",
        "4": "...HHHHHHHHHHHHPH.A.",
        "7": "...HHSEWSSSSEWSHH...",
        "9": "...HHSSSMMMMSSSHH..."
      }
    },
    "puzzled-2": {
      "from": "idle",
      "patch": {
        "1": "......HHHHHHHH...AA.",
        "2": "....HHHhhHHHHHHH...A",
        "3": "...HHHGwGGwGHHPPH.A.",
        "4": "...HHHHHHHHHHHHPH...",
        "5": "...HHSSSSSSSSSSHH.A.",
        "7": "...HHSEWSSSSEWSHH...",
        "9": "...HHSSSMMMMSSSHH..."
      }
    },
    "happy": {
      "from": "idle",
      "patch": {
        "0": "Y.........H.........",
        "1": ".Y....HHHHHHHH......",
        "4": "...HHHHHHHHHHHHPHHY.",
        "5": "...HHSSSSSSSSSSHH..Y",
        "7": "...HHESSESSESSEHH...",
        "8": "...HHBSSSSSSSSBHH..."
      }
    },
    "happy-2": {
      "from": "idle",
      "patch": {
        "1": "......HHHHHHHH.....Y",
        "2": ".Y..HHHhhHHHHHHH..Y.",
        "3": "Y..HHHGwGGwGHHPPH...",
        "7": "...HHESSESSESSEHH...",
        "8": "...HHBSSSSSSSSBHH..."
      }
    },
    "sleepy": {
      "from": "idle",
      "patch": {
        "0": "..........H......zzz",
        "1": "......HHHHHHHH....z.",
        "2": "....HHHhhHHHHHHH.zzz",
        "6": "...HHSSSSSSSSSSHH...",
        "7": "...HHSSSSSSSSSSHH...",
        "9": "...HHSSSSSMSSSSHH..."
      }
    },
    "sleepy-2": {
      "from": "idle",
      "patch": {
        "2": "....HHHhhHHHHHHH.zz.",
        "3": "...HHHGwGGwGHHPPHzz.",
        "6": "...HHSSSSSSSSSSHH...",
        "7": "...HHSSSSSSSSSSHH...",
        "9": "...HHSSSSSMSSSSHH..."
      }
    },
    "lookup": {
      "from": "idle",
      "patch": {
        "0": "..........H.......X.",
        "1": "......HHHHHHHH....X.",
        "2": "....HHHhhHHHHHHH..X.",
        "4": "...HHHHHHHHHHHHPHHX.",
        "9": "...HHSSSSRRSSSSHH..."
      }
    },
    "lookup-2": {
      "from": "idle",
      "patch": {
        "1": "......HHHHHHHH....X.",
        "2": "....HHHhhHHHHHHH..X.",
        "3": "...HHHGwGGwGHHPPH.X.",
        "5": "...HHSSSSSSSSSSHH.X.",
        "9": "...HHSSSSRRSSSSHH..."
      }
    }
  },
  "poses": {
    "idle": [["idle", 3600], ["idle-blink", 180], ["idle", 2400], ["idle-blink", 180], ["idle", 180], ["idle-blink", 180]],
    "reading": [["reading", 3000], ["reading-blink", 180], ["reading", 2400], ["reading-turn", 450], ["reading", 2200], ["reading-blink", 180]],
    "stamping": [["stamp-up", 600], ["stamp-down", 350], ["stamp-mark", 1100]],
    "ladder": [["search", 700], ["search-2", 700]],
    "puzzled": [["puzzled", 700], ["puzzled-2", 700]],
    "happy": [["happy", 500], ["happy-2", 500]],
    "sleepy": [["sleepy", 1400], ["sleepy-2", 1400]],
    "lookup": [["lookup", 600], ["lookup-2", 600]]
  }
} as const
