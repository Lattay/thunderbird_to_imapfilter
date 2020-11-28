# About

This is a quick and dirty converter from [Thunderbird](https://www.thunderbird.net) filters to [imapfilter](https://github.com/lefcha/imapfilter) config. 
It is nowhere near complete and only implements the few filters and actions I needed.
Yet, it should be fairly easy to add missing filters and actions (as long as they are supported by imapfilter).
It may also break with future versions of Thunderbird as I did not find any official specification for the file I parse.

Use at your own risk.

# How to use

This script only depends on python, (>= 3.5)

First you must localize your thunderbird configuration.
For linux, it is commonly found in one of the directory under `~/.thunderbird`.
You can found which one by looking in `~/.thunderbird/profiles.ini`.

Then, run the following command:
```bash
    python3 ./mt2if.py ~/.thunderbird/yourprofile_folder > config.lua
```

You should now open `config.lua` and tweak it a bit.
At the top of the file you should fill in you credentials.
The script try to produce a decent format, but you may want to modify it by hand too.

# Extending

I would be glad to help implementing missing conditions and actions from Thunderbird.
Please submit an issue on Github.
If you happen to have added yourself some missing part, I would be glad to merge it into this repository.
