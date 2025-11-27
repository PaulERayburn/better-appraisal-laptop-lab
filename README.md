# better-appraisal-laptop-lab
Originally known as the Best Buy Deal Finder Just in time for Black Friday shopping!!
The Better Appraisal Laptop Lab is a small experimental playground designed to show appraisers what becomes possible when we take control of our own technology using the tools available today. At its core, it’s a lightweight tool for finding potential laptop upgrade deals, either by parsing downloaded HTML pages with a long list of intially searched options or by querying Google Shopping through SERPAPI.

You can run it locally using your own downloaded HTML, or try the lightweight hosted version built with GitHub direct to Streamlit. If you want more power, you can plug in your own API key and take the tool further. It’s flexible by design: transparent, easy to inspect, and simple to modify.

This project began as a quick demo for my AIC-BC presentation Gen AI & the Appraiser. The idea wasn’t really about laptops; it was about demonstrating how modern AI-assisted coding tools (ClaudeCode, Codex, Gemini CLI, and others) enable appraisers to build their own utilities. These are tools created for appraisers, by appraisers, with clear logic and full control over how data is handled.

The broader message is straightforward: the profession is no longer limited to whatever software the market happens to provide. With today’s development tools, appraisers can create purpose-built utilities for their own use or as part of larger initiatives, and steadily raise the standard for the technology our work depends on.

If you’re interested in strengthening the appraisal community through open, transparent, appraiser-driven tools, feel free to explore the repo, fork it, run it locally, or contribute.
## How It Works
Keep in mind ongoing changes and updates may change the workflow but we will do our best to keep the README updated
Best Buy's website stores product data in a JSON blob embedded in the HTML. This tool:

1. Reads an HTML file you save from your browser
2. Extracts the product information (price, specs, savings)
3. Parses laptop specifications from product names
4. Compares each laptop against your current computer's specs
5. Shows you which laptops are upgrades and ranks them by value

## Quick Start

### Step 1: Prepare the Best Buy Page

1. Go to [Best Buy Canada Laptops](https://www.bestbuy.ca/en-ca/category/laptops-macbooks/20352) (or any laptop category page)

2. **Refine your search** using filters on the left side:
   - Set a price range that covers what you're looking for
   - Filter by brand, screen size, or other specs if desired
   - Use the widest range that still includes what you want

3. **Load all products** by clicking the **"Show More"** button at the bottom of the page
   - Keep clicking until all products you want are visible
   - The page loads products dynamically, so you need them on screen to capture them

4. **Save the page:**

   **Chrome:**
   - Click the three dots menu (top right) `⋮`
   - Go to **Cast, save, and share** (or **More tools**)
   - Select **Save page as...**
   - Choose **"Webpage, Complete"** and save to a folder

   **Firefox:**
   - Click the hamburger menu (top right) `≡`
   - Select **Save Page As...**
   - Choose **"Web Page, complete"**

   **Edge:**
   - Click the three dots menu (top right) `...`
   - Select **Save page as**
   - Choose **"Webpage, Complete"**

   **Keyboard shortcut (all browsers):**
   - `Ctrl+S` (Windows) or `Cmd+S` (Mac)

### Step 2: Run the Script

```bash
# Basic usage - uses default specs (16GB RAM, 512GB storage, Gen 10 CPU)
python bestbuy_deal_finder.py --html "Laptops & MacBooks _ Computers & Tablets _ Best Buy Canada.html"

# With your actual current specs
python bestbuy_deal_finder.py --html "saved_page.html" --ram 16 --storage 1800 --cpu-gen 10

# Generate a nice HTML wishlist
python bestbuy_deal_finder.py --html "saved_page.html" --ram 16 --storage 1024 --cpu-gen 10 --wishlist
```

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--html`, `-f` | Path to the saved HTML file (required) | - |
| `--ram` | Your current RAM in GB | 16 |
| `--storage` | Your current storage in GB | 512 |
| `--cpu-gen` | Your current CPU generation (e.g., 10 for 10th gen Intel) | 10 |
| `--all` | Show all products, not just upgrades | False |
| `--wishlist`, `-w` | Generate an HTML wishlist file | False |
| `--output`, `-o` | Output path for wishlist HTML | wishlist.html |
| `--top` | Number of deals to include in wishlist | 3 |

## Example Output

```
Loading products from: laptops.html
Found 24 products

Your current specs: CPU Gen 10, RAM 16GB, Storage 1800GB
Finding upgrades...
Found 15 potential upgrades

====================================================================================================
LAPTOP DEALS - Compared to your specs: CPU Gen 10, RAM 16GB, Storage 1800GB
====================================================================================================
Name                                                       |      Price |    Savings | Notes
----------------------------------------------------------------------------------------------------
Acer Nitro V 15.6" FHD Gaming Laptop, Intel Core i7-136... | $ 1,599.99 |       $800 | CPU+ (Gen 13), RAM+ (32GB), Storage+ (2048GB)
Acer Nitro 15.6" FHD Gaming Laptop, Intel Core i7-13620... | $ 1,929.99 |       $920 | CPU+ (Gen 13), RAM+ (64GB), Storage+ (4096GB)
...

************************************************************
  BEST UPGRADE DEAL FOUND
************************************************************
  Product: Acer Nitro V 15.6" FHD Gaming Laptop...
  Price:   $1,599.99
  Savings: $800
  Specs:   CPU Gen 13, RAM 32GB, Storage 2048GB, GPU: RTX 5060
  Link:    https://www.bestbuy.ca/en-ca/product/19506671
************************************************************
```

## Requirements

- Python 3.6 or higher
- No external dependencies! Uses only Python standard library (`json`, `re`, `argparse`)

## Finding Your Current Specs

### Windows
1. Press `Win + I` to open Settings
2. Go to System > About
3. Note your processor, RAM, and check storage in "This PC"

### Mac
1. Click Apple menu > About This Mac
2. Your specs are shown on the Overview tab

### What's My CPU Generation?

| CPU Model | Generation |
|-----------|------------|
| Intel Core i7-10750H | 10th Gen |
| Intel Core i7-11800H | 11th Gen |
| Intel Core i7-12700H | 12th Gen |
| Intel Core i7-13620H | 13th Gen |
| Intel Core Ultra 7 | 14th Gen+ |

## How Scoring Works

The tool ranks deals by an "upgrade score":

- **+2 points** - Better CPU generation
- **+2 points** - More RAM
- **+1 point** - More/equal storage
- **+1 point** - Has a sale discount

Higher scores appear first. When scores tie, cheaper laptops rank higher.

## Limitations

- **Best Buy Canada works best** - Full product data is embedded in saved pages
- **Best Buy US is experimental** - US site uses dynamic JavaScript loading, so only a few products may be captured when saving the page
- Spec parsing works best with gaming laptops that list specs in the title
- Some specs may not be detected if they're formatted unusually
- Only compares laptops currently shown on the saved page

## Project Files

- `app.py` - Streamlit web app (hosted version)
- `bestbuy_deal_finder.py` - Command line script (for advanced users)

## Contributing

Feel free to open issues or pull requests! Some ideas for improvements:

- Support for other retailers (Amazon, Newegg, etc.)
- Better spec detection for AMD processors
- Price history tracking
- Email/notification when deals appear

## License

MIT License - Use freely, modify as needed, no warranty provided.

---

*Originally created to help find laptop upgrade deals during Black Friday sales!*
