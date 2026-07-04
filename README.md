# Overview
MassSpectrum-Analyzer is a tool for analysis of peptide spectral data. Load raw files (.raw / .mzML), search data (psm search outputs) 
and begin annotating entire datasets. The spectral annotation tool provides full control on what fragment ions you wish to annotate, with generation of neutral loss ions,
remainder ions, labile ions (complete loss of modification), and user custom offsets. Spectra can be tracked and exported in bulk as you analyse your data to enable large-scale analysis. The tool allows
for comparison of fragment ions between spectra, hydrogen migration analysis, rescoring of datasets, and protein coverage visualisation.
<img width="1644" height="879" alt="image" src="https://github.com/user-attachments/assets/25f123f3-11ca-427f-ba81-160bebc94ff9" />

Example of GUI with glycopeptide from A. baumannii BAL062 annotated with non-labile and labile species (~), and Y-glycan ions


## Getting started
Download the latest release from https://github.com/Kristian-Karlic/MassSpectrum-Analyzer/releases/tag/v1.0.0
Unzip compressed software, and simply run by launching the .exe to get started annotating.

### 📊 Data Input & Compatibility

MassSpectrum Analyzer currently supports a variety of PSM search inputs that can be imported into the program. 
The user can load raw files and corresponding PSM files containing PSM identifications within the manage files tab. When the users "Prepare Data" it will extract all spectral information (m/z, intensity, scan header etc.).
The user will then be prompted to save the experiment, which will store all the PSMs and their corresponding spectral information, which allows experiments to be reloaded quickly the next time they launch the application without the need to extract
any data again for the same experiment. 
<img width="1264" height="879" alt="image" src="https://github.com/user-attachments/assets/7a6dfc7d-7588-4510-a377-a637cac00bb3" />

**Raw Data Files:**
- **Thermo Fisher RAW files** (`.raw`) — Native support via RawFileReader libraries
- **mzML files** (`.mzml`) — Standard XML-based mass spectrometry format

**Search Engine Results:**
The application can import and normalize PSM data from multiple search engines:
- **MSFragger** — PSM validation and pre-validation formats (`psm.tsv` / `no PSM validation.tsv`)
- **MaxQuant** — Evidence and PSM tables (`msms.txt`)
- **MetaMorpheus** — PSM output files (`AllPSMs.psmtsv` / `AllPeptides.psmtsv`)
- **Byonic** — Search results (`.CSV` exports from byonic viewer)
- **psm_utils** — Universal PSM format (`.pep.xml`/`.idXML`/`.XML`/`.mzid`/`.pin`/`.pout`) (https://github.com/compomics/psm_utils)

### Peptide Fragmentation & Ion Analysis

- **Comprehensive ion type support:**
  - Standard ions: a, b, c, x, y, z series
  - Hydrogen migration variants: c-1, z+1
  - Satellite ions: d, w, v 
  - Internal fragments (a/b)
  - Precursor ions (MH)
  - Glycan Y-ions (SNFG shapes support with Unicode) (Glycan database, custom monosaccharides)

 <img width="613" height="425" alt="image" src="https://github.com/user-attachments/assets/5ada7cfd-bc14-4434-bcea-c781dd3aa865" />

   - Standard losses: H₂O, NH₃, H₃PO₄, SOCH₄, CO
    - Custom ion series with user-defined offsets and AA site restrictions
  - Modification database
    - Neutral losses (e.g. Phospho -97.977 Da - y* series)
    - Labile losses (e.g. O-glyco complete loss - y~ series)
    - Remainder ions (e.g. N-glyco 203 Da - y^ series)
   <img width="763" height="408" alt="image" src="https://github.com/user-attachments/assets/d7b9b78f-a60b-4d99-93f6-2b42e04621de" />

  - Isotope peak generation (+1 to +4 Isotopes)
  - Diagnostic Ions (e.g. Oxonium ions)

### Spectral annoation
* PSMs loaded in from search input can be accessed via the table below the spectra. Simply click a row within the table, and it the PSM will be annotated with the ions you've selected
* The spectra is fully interactive, allowing movement of text label, tooltips as hover over peaks, alternative matches within ppm tolerance, hide/show certain ion groups, change colours etc.
* The interactive peptide sequence allows movement of modifications to reannotate the peptide adaptively to figure out best annotation. Additionally when exporting this information will be tracked.
* Ability to relocalise a modification across every position on a peptide to determine highest scoring position
* Various scoring parameters can be used to determine quality of spectra
  * X!Tandem score (Craig, R., & Beavis, R. C. (2004). TANDEM: matching proteins with tandem mass spectra. Bioinformatics, 20(9), 1466-1467.)
  * Complementary Ion series (N-/C- series detected at unique positions
  * Consecutive Pairs (y1,y2,y3,y4 etc.)
  * Theoritical Fragments (Number of matched ions / total ions in search space)
  * Peaks annotated (Number of matched peaks / total number of peaks)
  * Annotated TIC (%) (Percentage of TIC that is matched)
  * Coverage (Number of fragmented bonds for peptide)
  * Intact Coverage (no labile, remainder or neutral losses considered)  
  * Partial Coverage (all ions expect labile ions)
  * Ion counts (split into different species for each main ion type (y/b/a etc.)
  * Ion Intensities (the percent intensities of each species for each main ion type (e.g. y/y-H2O/y* etc.)
<img width="371" height="487" alt="image" src="https://github.com/user-attachments/assets/54104c0e-fb3d-45f3-a0a4-5cedc44facdb" />


* Specific scan numbers can also be used to extract m/z and intensity values (useful for cases such as PRM where it may not be identified within psm.tsv)
* Distance between peaks can be measured by pressing "M" then selecting two peaks
* Annotations can also be deleted by right clicking and selecting delete
* Spectral annotations can be tracked to create a list of accepted/bad spectra which can later be exported
  * Spectral annotations can either be exported as an .svg or .svg/data (which includes psm information). Addtionally if added to bulk export spectral annotations can be exported in bulk through export list.
 
### Fragmentation Anaylsis
* Ion count: Groups can be created where you can drag and drop peptides from the psm table to make comparisons of the number of ions detected. Multiple peptides can be added to a group, so replicate information can be used. Data or graph can be exported for downstream analysis
* Isotopem ratio: The ratio of isotopes for particular peptide positions can be calculated - this tool is built for specific anaylsis of hydrogen transfer within c/z ions
  
### Rescore 
* Rescore allows you to take all the specific ions that you want to use for annotation and calculate all scoring features that are available. The rescore statistics can then be viewed within the app, and the entire dataframe can also be exported. This exported dataframe can also be exported with ion counts, matched ions and their intensities for global fragmentation analysis.
* Additionally hydrogen migration can be exported for entire datasets if selected
* A basic graphing of rescore information can be viewed within the app, but more detailed analysis can be done with the exported data.
  <img width="1157" height="1115" alt="image" src="https://github.com/user-attachments/assets/3383b4b7-91bb-45aa-8198-d1351345bd9e" />

### Protein Coverage
* A fasta file that contains the same identifiers as found within your PSM data can be used to visualise protein coverage across your data
<img width="1211" height="995" alt="image" src="https://github.com/user-attachments/assets/ce878375-3415-4bf0-9a3e-c137ca12fd5a" />


## Requirements for .exe
- Windows 10/11
- .NET Framework 4.7.1 (for ThermoFisher raw file support)

## Running from source on Linux/macOS
The GUI can be run from source on Linux and macOS with Python and the packages
in `requirements.txt`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python GUI.py
```

For mzML-only workflows, no .NET runtime is needed. Thermo Fisher `.raw` files
use pythonnet and Thermo RawFileReader. On Linux/macOS this requires either a
working Mono runtime for the bundled `Net471` assemblies or a .NET/CoreCLR
runtime for the bundled .NET Core assemblies.


MassSpectrum-Analyzer utilises RawFileReader for accessing spectral information from .raw files.
RawFileReader reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. All rights reserved
