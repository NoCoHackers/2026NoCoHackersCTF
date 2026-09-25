# Ghost in the Index - author's write-up

**Flag:** declared in `challenge.yml`

## Intended path

The page looks like ordinary text, but every word (for the length of the flag) is followed by an invisible Unicode tag character (U+E0000..U+E007F). 
The offset matchs ASCII, so subtracting 0xE0000 from
each byte produces the flag.

1. The hint mentions a larger character set. This is a loose reference to unicode.
2. Checking the page source with hexdump or a text editor configured to show placeholders for invisible characters. Could serve as further confirmation.
3. Extract the tag characters and subtract 0xE0000 from each character and display as ascii.

### CyberChef Decode
1. Using regex extract the unicode tags
2. Munge the text for further processing (remove newlines)
3. To charcode (base 16)
4. Remove 0e00
5. Convert from hex to ascii

In the following cyberchef link, I have disabled a few "To Hex" items. Enable those and disable all the transforms that follow to see how the bytes change as we process the text.

(cyberchef)["https://cyberchef.io/#recipe=To_Hex('Space',0/disabled)Regular_expression('User%20defined','%5C%5CuDB40%5B%5C%5CuDC20-%5C%5CuDC7E%5D',true,true,false,false,false,false,'List%20matches')To_Hex('Space',0/disabled)Find_/_Replace(%7B'option':'Regex','string':'%5C%5Cn'%7D,'',true,false,true,false)To_Hex('Space',0/disabled)To_Charcode('Space',16)Find_/_Replace(%7B'option':'Regex','string':'0e00'%7D,'',true,false,true,false)From_Hex('Auto')&input=SfOgga4gY2Fu86CBryBmZWVs86CBoyB0aGVtLPOgga8gYnV086CBuyBJ86CAuSBjYW5ub3TzoIC3IHNlZfOggLAgdGhlbS7zoIC4CgpB86CBoyBjaGlsbPOggLcgaW7zoICzIG1586CBoSBib25lcy7zoIC4CgpB86CAsCB0aW5nbGXzoIGiIGlu86CBpCBtefOggaYgc3BpbmUu86CBogoKVGhlefOggaIgd2Fsa/OggLMgdGhl86CAuSBzdHJlZXRz86CAtSB3aXRo86CBpiBtZS7zoICyCgpJ86CAtCBzd2VhcvOggLkgb25l86CBoyBvbmNl86CBpCBzaG92ZWTzoIC3IG1l86CAuCBvZmbzoIGlIG1586CAtCBiaWtlLvOggLgKCknzoICwIGR1c3RlZPOggLkgbXlzZWxm86CAtCBvZmYs86CBvSBidXQgbm9ib2R5IHdhcyBhcm91bmQuCgpOb2JvZHkgYmVsaWV2ZXMgbWUuCgpBbSBJIGNyYXp5PwoKRXZlbiBub3cgYXMgSSB0eXBlIHRoZSB3b3JkcyBvbiB0aGlzIHBhZ2UsIEkgY2FuIGZlZWwgdGhlaXIgaW5mbHVlbmNlCgpUaGVpciBjaGFyYWN0ZXIgc2V0IHNlZW1zIGJyb2FkZXIgdGhhbiBtaW5lLgoKSW52aXNpYmxlIHRvIHRoZSBuYWtlZCBleWUsIGJ1dCBzdGlsbCB0aGVyZS4"]

### Python (LLM Generated)
`solution/encode.py --decode` regenerates the flag from the page source;
`solution/solve.sh` does the same against the live site.

