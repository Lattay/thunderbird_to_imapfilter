# About

This is a quick and dirty converter from [Thunderbird](https://www.thunderbird.net) filters to [imapfilter](https://github.com/lefcha/imapfilter) config.
It is nowhere near complete and only implements the few filters and actions I needed.
Yet, it should be fairly easy to add missing filters and actions (as long as they are supported by imapfilter).
It may also break with future versions of Thunderbird as I did not find any official specification for the parsed file.

Use at your own risk.

# How to use

This script only depends on python, (>= 3.7)

1. Localize your thunderbird configuration.
On linux, it is commonly found in one of the directory under `~/.thunderbird`.
You can find which one by looking in `~/.thunderbird/profiles.ini`.
2. Run the following command:
```bash
    python3 ./mt2if.py ~/.thunderbird/yourprofile_folder > config.lua
```
3. Open `config.lua` and tweak it to your liking.
You need to fill in the credentials at the top of the file.
The script tries to produce a decent format, but you may want to modify it by hand too.

# Extending

I am open to suggestions and contributions, please discuss them on the [issue tracker](https://github.com/Lattay/thunderbird_to_imapfilter/issues).

New conditions can be implemented in `parse_condition`.
New actions can be implemented in `render_action`.
