# Overview
MassSpectrum-Analyzer is a tool for analysis of peptide spectral data. Load raw files (.raw / .mzML), search data (psm search outputs) 
and begin annotating entire datasets. The spectral annotation tool provides full control on what fragment ions you wish to annotate, with generation of neutral loss ions,
remainder ions, labile ions (complete loss of modification), and user custom offsets. Spectra can be tracked and exported in bulk as you analyse your data to enable bulk analysis. The tool allows
for comparison of fragment ions between spectra, rescoring of datasets using (X!Tandem), protein coverage visualisation.

## Getting started
Download the latest release from https://github.com/Kristian-Karlic/MassSpectrum-Analyzer/releases/tag/pre-release

### 📊 Data Input & Compatibility

**Raw Data Files:**
- **Thermo Fisher RAW files** (`.raw`) — Native support via RawFileReader libraries
- **mzML files** (`.mzml`) — Standard XML-based mass spectrometry format

**Search Engine Results:**
The application can import and normalize PSM data from multiple search engines:
- **MSFragger** — PSM validation and pre-validation formats (psm.tsv / pre-validation TSV)
- **MaxQuant** — Evidence and PSM tables (msms.txt)
- **MetaMorpheus** — PSM output files (AllPSMs.psmtsv / AllPeptides.psmtsv)
- **Byonic** — Search results (.CSV exports from byonic viewer)
- **psm_utils** — Universal PSM format (.pep.xml/.idXML/.XML/.mzid.pin /.pout)
  
### Peptide Fragmentation & Ion Analysis

- **Comprehensive ion type support:**
  - Standard ions: a, b, c, x, y, z series
  - Variants: c-1, z+1
  - Satellite ions: d, w, v (with amino acid sidechain losses)
  - Internal fragments (a/b)
  - Precursor ions (MH)
  - Custom ion series with user-defined offsets and restrictions
  - Standard losses: H₂O, NH₃, H₃PO₄, SOCH₄, CO
  - Modification-specific neutral losses
  - Labile losses and remainder ions
  - Multi-stack neutral losses (e.g., -2H₂O)
  - Isotope peak generation (+1 to +4 Isotopes)
  - Diagnostic Ions

### Spectral annoation
* Interactive Annotation
* Select rows from the dataframe to annotate the selected peptide (m/z and intensity values can be added manually and annotated as well)
* a/b/c/c-1/y/z/z+1/x/MH/int-b/int-a ions available
* Several neutral losses available by default and the level of neutral losses allowed can be modified
* Diagnostic ions - A database of diagnostic ions can be added and selected for annotation (Edit the list within the "Edit" menu tab)
* Custom ion series - A database of custom ion series can be added and selected for annotation (Edit the list within the "Edit" menu tab). This allows the user to add custom offsets to create a custom ion series where multiple can be added and annotated along with standard ions
* Specific scan numbers can also be used to extract m/z and intensity values (useful for cases such as PRM where it may not be identified within psm.tsv)
* Modifications can be added/dragged/deleted on the peptide sequence allowing for on the go annotation to see how the position of the modification position affects the peptide fragmentation
* Distance between peaks can be measured by pressing "M" then selecting two peaks
* Annotations can also be deleted by right clicking and selecting delete
* Spectral annotations can be tracked to create a list of accepted/bad spectra which can later be exported
* Spectral annotations can either be exported as an .svg or .svg/data (which includes psm information). Addtionally if added to bulk export spectral annotations can be exported in bulk
### Fragmentation Anaylsis
* Ion count: Groups can be created where you can drag and drop peptides from the psm table to make comparisons of the number of ions detected. Multiple peptides can be added to a group, so replicate information can be used. Data or graph can be exported for downstream analysis
* Isotopem ratio: The ratio of isotopes for particular peptide positions can be calculated - this tool is built for specific anaylsis of hydrogen transfer within c/z ions
### Rescore 
* Rescore allows you to take all the specific ions that you want to use for annotation and apply them to a X!Tandem method (Craig, R., & Beavis, R. C. (2004). TANDEM: matching proteins with tandem mass spectra. Bioinformatics, 20(9), 1466-1467.). The rescore statistics can then be viewed within the app, and the entire dataframe can also be exported. This exported dataframe also provides annotated TIC and ion counts for all selected ions used during the rescore which can be used for more global analysis of fragmentation comparison
### Protein Coverage
* A fasta file that contains the same identifiers as found within your PSM data can be used to visualise protein coverage across your data


## Requirements for .exe
- Windows 10/11
- .NET Framework 4.7.1 (for ThermoFisher raw file support)


MassSpectrum-Analyzer utilises RawFileReader for accessing spectral information from .raw files.
RawFileReader reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. All rights reserved
