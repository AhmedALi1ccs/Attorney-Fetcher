import streamlit as st
import pandas as pd
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import io

# Streamlit App Configuration
st.set_page_config(
    page_title="Attorney Data Fetcher",
    page_icon="⚖️",
    layout="wide"
)

# ===== UTILITY FUNCTIONS =====

def parse_case_number(case_num_str):
    """Parse case number string to extract year, case type, and sequence number."""
    if not case_num_str or pd.isna(case_num_str):
        return None
    
    # Clean the string and remove anything in brackets
    clean_case = re.sub(r'\s*\([^)]*\)', '', str(case_num_str).strip())
    
    # Pattern to match: 2-digit year + 2-letter case type + numbers
    pattern = r'^(\d{2})([A-Z]{2})(\d+)$'
    match = re.match(pattern, clean_case)
    
    if match:
        year = match.group(1)
        case_type = match.group(2)
        sequence = match.group(3).zfill(7)  # Pad with zeros to 7 digits
        
        return {
            'year': year,
            'case_type': case_type,
            'sequence': sequence,
            'original': case_num_str
        }
    
    return None

def setup_browser(headless=True):
    """Set up Chrome WebDriver with fast settings."""
    options = webdriver.ChromeOptions()
    
    if headless:
        options.add_argument('--headless')
    
    # Fast browser options
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins')
    options.add_argument('--disable-images')  # Faster loading
    options.add_argument('--window-size=1280,720')  # Smaller window
    options.add_argument('--log-level=3')  # Reduce logging
    options.add_argument('--silent')
    
    # Quick initialization
    try:
        print("🔧 Starting browser...")
        driver = webdriver.Chrome(options=options)
        
        # Set short timeouts
        driver.set_page_load_timeout(20)
        driver.implicitly_wait(5)
        
        print("✅ Browser ready")
        return driver
        
    except Exception as e:
        raise Exception(f"Browser failed to start: {e}")

def handle_disclaimer(driver, max_retries=2):
    """Handle the disclaimer page with shorter timeouts."""
    url = "https://fcdcfcjs.co.franklin.oh.us/CaseInformationOnline/acceptDisclaimer?-1a3802dfior9hh"
    
    for attempt in range(max_retries):
        try:
            print(f"🌐 Disclaimer attempt {attempt + 1}/{max_retries}")
            
            # Navigate with timeout
            driver.set_page_load_timeout(15)
            driver.get(url)
            
            # Wait for form with shorter timeout
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.TAG_NAME, "form"))
            )
            print("📝 Disclaimer form found")
            
            # Try clicking accept button quickly
            accept_selectors = [
                "//input[@type='submit']",
                "//input[contains(@value, 'Accept')]",
                "//button[contains(text(), 'Accept')]"
            ]
            
            button_clicked = False
            for selector in accept_selectors:
                try:
                    accept_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    accept_button.click()
                    print(f"✅ Clicked disclaimer button")
                    button_clicked = True
                    break
                except:
                    continue
            
            if not button_clicked:
                # Try form submit
                form = driver.find_element(By.TAG_NAME, "form")
                form.submit()
                print("📤 Submitted form directly")
            
            # Wait for search form with shorter timeout
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.NAME, "caseYear"))
            )
            print("✅ Reached search form")
            return True
                
        except Exception as e:
            print(f"❌ Disclaimer attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                return False
            time.sleep(1)
    
    return False

def fill_search_form(driver, case_year, case_type, case_sequence):
    """Fill the search form with shorter timeouts."""
    try:
        print(f"📝 Filling: {case_year}{case_type}{case_sequence}")
        
        # Set shorter timeouts
        driver.implicitly_wait(3)
        
        # Fill case year
        case_year_input = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.NAME, "caseYear"))
        )
        case_year_input.clear()
        case_year_input.send_keys(case_year)
        
        # Select case type
        case_type_select = Select(WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.NAME, "caseType"))
        ))
        case_type_select.select_by_value(case_type)
        
        # Fill case sequence
        case_seq_input = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.NAME, "caseSeq"))
        )
        case_seq_input.clear()
        case_seq_input.send_keys(case_sequence)
        
        # Submit
        case_seq_input.send_keys(Keys.ENTER)
        print("✅ Form submitted")
        
        # Short wait for results
        time.sleep(2)
        return True
        
    except Exception as e:
        print(f"❌ Form fill error: {e}")
        return False

# ===== ENHANCED DEFENDANT AND ATTORNEY EXTRACTION FUNCTIONS =====

def is_company(name):
    """Check if a name appears to be a company rather than an individual."""
    company_patterns = [
        # Legal entities
        r'\b(llc|inc|corp|ltd|llp|lp|plc)\b',
        r'\bl\.?l\.?c\.?\b',  # Handles L.L.C., LLC, etc.
        r'\bl\.?l\.?p\.?\b',  # Handles L.L.P., LLP, etc.
        r'\b(limited|incorporated|corporation)\b',
        r'\bp\.?c\.?\b',  # Professional Corporation
        r'\bd\.?b\.?a\.?\b',  # Doing Business As
        
        # Financial/Banking
        r'\b(bank|trust company|banking|financial|credit union)\b',
        r'\b(investment[s]?|fund|capital|securities|wealth)\b',
        r'\b(mortgage|loan|finance|lending|leasing)\b',
        
        # Business types
        r'\b(company|companies|group|associates)\b',
        r'\b(partners|properties|solutions|systems)\b',
        r'\b(enterprises|ventures|industries)\b',
        r'\b(holdings|global|international)\b',
        r'\b(realty|construction|development)\b',
        r'\b(management|consulting|services)\b',
        r'\b(agency|firm|bureau|institute)\b',
        
        # Organizations
        r'\b(foundation|association|society|alliance)\b',
        r'\b(network|organization|federation|coalition)\b',
        r'\b(committee|commission|authority|council)\b',
        r'\b(department|division|branch|unit)\b',
        
        # Educational/Medical
        r'\b(school|university|college|academy)\b',
        r'\b(hospital|clinic|medical|healthcare)\b',
        r'\b(center|centre|laboratory)\b',
        
        # Religious/Nonprofit
        r'\b(church|ministry|temple|mosque)\b',
        r'\b(charity|nonprofit|ngo)\b',
        
        # Government entities
        r'\b(county|city|state|federal|bureau|department)\b',
        r'\b(united states|usa|u\.s\.a\.|u\.s\.|us)\b',
        
        # Additional specific patterns
        r'unknown spouse',
        r'unknown tenant',
        r'unknown occupant',
        r'john doe',
        r'jane doe',
        r'et al',
    ]
    
    pattern = '|'.join(company_patterns)
    
    # Check if any company pattern matches
    if re.search(pattern, name, re.IGNORECASE):
        return True
    
    # Additional checks for company-like structures
    company_indicators = [
        name.count('&') > 0,  # Contains &
        name.count(',') > 1,  # Multiple commas often indicate business listings
        bool(re.search(r'\d', name)),  # Contains numbers
        len(name.split()) > 4,  # Very long names are usually organizations
    ]
    
    return any(company_indicators)

def find_main_defendant(defendants):
    """Find the main defendant from a list of defendants (individual, not company)."""
    if not defendants:
        return "No defendants found"
    
    # First, try to filter out company-like defendants to find individuals
    individual_defendants = [name for name in defendants if not is_company(name)]
    
    # If we found any individuals, return the first one
    if individual_defendants:
        print(f"🎯 Found individual defendant: {individual_defendants[0]}")
        return individual_defendants[0]
    
    # If no individuals were found, use the first defendant as fallback
    print(f"⚠️ No individual defendants found, using first defendant: {defendants[0]}")
    return defendants[0]

# Remove the old complex functions - replaced with fast versions above

def extract_attorney_data(driver):
    """Fast attorney data extraction with timeouts."""
    start_time = time.time()
    TIMEOUT_SECONDS = 30  # Maximum 30 seconds per case
    
    attorney_data = {
        'attorney_name': '',
        'attorney_firm': '',
        'attorney_address': '',
        'attorney_phone': '',
        'service_type': '',
        'service_date': '',
        'certified_mail_no': '',
        'defendant_name': '',
        'defendant_address': '',
        'service_status': '',
        'main_defendant': '',
        'all_defendants': '',
        'defendant_count': 0,
        'service_match': '',  # New field to track which defendant's attorney we found
        'extraction_status': 'Not Found'
    }
    
    try:
        # Check timeout before each major step
        if time.time() - start_time > TIMEOUT_SECONDS:
            attorney_data['extraction_status'] = 'Timeout - Overall Process'
            return attorney_data
        
        print("🔍 Step 1: Quick defendant extraction...")
        defendants = extract_all_defendants_fast(driver)
        
        if time.time() - start_time > TIMEOUT_SECONDS:
            attorney_data['extraction_status'] = 'Timeout - After Defendants'
            return attorney_data
        
        if not defendants:
            attorney_data['extraction_status'] = 'No Defendants Found'
            return attorney_data
        
        print("🎯 Step 2: Finding main defendant...")
        main_defendant = find_main_defendant(defendants)
        
        attorney_data['all_defendants'] = '; '.join(defendants)
        attorney_data['defendant_count'] = len(defendants)
        attorney_data['main_defendant'] = main_defendant
        
        if main_defendant == "No defendants found":
            attorney_data['extraction_status'] = 'No Defendants Found'
            return attorney_data
        
        if time.time() - start_time > TIMEOUT_SECONDS:
            attorney_data['extraction_status'] = 'Timeout - Before Service Search'
            return attorney_data
        
        print("📄 Step 3: Quick service search...")
        service_details = find_proof_of_service_fast(driver, main_defendant)
        
        if service_details:
            print("✅ Extracting attorney info...")
            
            # Quick mapping
            attorney_data['service_type'] = service_details.get('service_delivery_method', '')
            attorney_data['defendant_name'] = service_details.get('service_name', '')
            attorney_data['attorney_name'] = service_details.get('service_attorney_name', '')
            
            # Check if we found service for main defendant or fallback defendant
            served_defendant = service_details.get('service_name', '')
            if main_defendant.lower() in served_defendant.lower() or served_defendant.lower() in main_defendant.lower():
                attorney_data['service_match'] = 'Main Defendant'
                print(f"📋 Attorney info from main defendant: {served_defendant}")
            else:
                attorney_data['service_match'] = 'Other Human Defendant'
                print(f"📋 Attorney info from other human defendant: {served_defendant}")
            
            # Quick attorney address parsing
            attorney_address = service_details.get('service_attorney_address', '')
            if attorney_address:
                lines = attorney_address.replace('\n', '|').split('|')
                if lines:
                    attorney_data['attorney_firm'] = lines[0].strip()
                    if len(lines) > 1:
                        attorney_data['attorney_address'] = ' '.join(lines[1:]).strip()
                
                # Quick phone extraction
                phone_match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', attorney_address)
                if phone_match:
                    attorney_data['attorney_phone'] = phone_match.group(0)
            
            attorney_data['extraction_status'] = 'Found'
            print(f"✅ Success: {attorney_data['attorney_name']} (via {attorney_data.get('service_match', 'Unknown')})")
            
        else:
            attorney_data['extraction_status'] = 'No Service Records Found'
    
    except Exception as e:
        print(f"❌ Error: {e}")
        attorney_data['extraction_status'] = f'Error: {str(e)}'
    
    elapsed = time.time() - start_time
    print(f"⏱️ Extraction took {elapsed:.1f} seconds")
    return attorney_data

def extract_all_defendants_fast(driver):
    """Fast defendant extraction with timeout."""
    defendants = []
    try:
        # Set short timeout
        driver.implicitly_wait(2)
        
        # Quick check for defendant table
        defendant_body = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "defendant-body"))
        )
        
        # Get defendant rows quickly
        defendant_rows = defendant_body.find_elements(By.XPATH, ".//tr[not(contains(@id, 'defdetail'))]")
        
        for def_row in defendant_rows:
            try:
                def_cells = def_row.find_elements(By.TAG_NAME, "td")
                if len(def_cells) >= 2:
                    defendant_name = def_cells[1].text.strip()
                    if defendant_name:
                        defendants.append(defendant_name)
            except:
                continue
        
        print(f"Found {len(defendants)} defendants")
        
    except Exception as e:
        print(f"Error extracting defendants: {e}")
    
    return defendants

def find_proof_of_service_fast(driver, main_defendant_name):
    """Fast service search with human defendant fallback."""
    try:
        # Set short timeout
        driver.implicitly_wait(2)
        
        # Quick navigation to docket
        try:
            docket_links = driver.find_elements(By.XPATH, 
                "//a[contains(text(), 'Docket') or contains(text(), 'Documents')]")
            if docket_links:
                docket_links[0].click()
                time.sleep(1)
        except:
            pass

        # Quick service search
        service_types = ['CERTIFIED MAIL', 'PROCESS SERVER']
        
        for service_type in service_types:
            service_xpath = f"//td[contains(text(), 'PROOF OF SERVICE ISSUED - {service_type}')]/parent::tr"
            service_rows = driver.find_elements(By.XPATH, service_xpath)
            
            if not service_rows:
                continue

            print(f"🔍 Checking {len(service_rows)} {service_type} entries...")
            
            # STEP 1: Try to find service for main defendant first
            main_defendant_service = None
            
            # Check first 5 service entries for speed
            for idx, row in enumerate(service_rows[:5]):
                try:
                    service_details = extract_service_details_fast(driver, row, service_type)
                    if not service_details:
                        continue
                    
                    # Check if this matches main defendant
                    name_match = service_details.get("service_name", "").lower()
                    if (main_defendant_name.lower() in name_match or name_match in main_defendant_name.lower()):
                        print(f"✅ Found service for main defendant: {name_match}")
                        return service_details
                        
                except Exception as e:
                    print(f"Error checking service entry {idx+1}: {e}")
                    continue
            
            # STEP 2: Fallback - look for ANY human defendant with service
            print(f"⚠️ No service found for main defendant, checking other human defendants...")
            
            for idx, row in enumerate(service_rows[:5]):
                try:
                    service_details = extract_service_details_fast(driver, row, service_type)
                    if not service_details:
                        continue
                    
                    # Check if this defendant is human (not company)
                    defendant_name = service_details.get("service_name", "")
                    if defendant_name and not is_company(defendant_name):
                        print(f"✅ Found service for human defendant: {defendant_name}")
                        return service_details
                        
                except Exception as e:
                    print(f"Error checking fallback service entry {idx+1}: {e}")
                    continue

        print("❌ No service found for main defendant or other human defendants")
        return None

    except Exception as e:
        print(f"Service search error: {e}")
        return None

def extract_service_details_fast(driver, row, service_type):
    """Fast extraction of service details from a single row."""
    try:
        expand_img = row.find_element(By.XPATH, ".//img[contains(@id, 'docimg')]")
        doc_id = expand_img.get_attribute("id")
        doc_num = doc_id.replace("docimg", "")
        
        expand_img.click()
        time.sleep(0.3)

        doc_table_id = f"doctable{doc_num}"
        doc_table = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.ID, doc_table_id))
        )

        service_details = {"service_delivery_method": service_type}
        
        # Quick data extraction
        rows = doc_table.find_elements(By.TAG_NAME, "tr")
        for r in rows:
            cells = r.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 2:
                label = cells[0].text.strip().rstrip(':').lower().replace(" ", "_")
                value = cells[1].text.strip()
                if label:
                    service_details[f"service_{label}"] = value

        # Collapse the detail
        expand_img.click()
        time.sleep(0.2)
        
        return service_details
        
    except Exception as e:
        print(f"Error extracting service details: {e}")
        return None

# ===== MAIN STREAMLIT APP =====

st.title("⚖️ Attorney Data Fetcher - Franklin County Court")
st.markdown("Upload a CSV file with Case # column to fetch attorney information from court records")

# File Upload Section
st.subheader("📁 Upload CSV File")
uploaded_file = st.file_uploader(
    "Choose a CSV file", 
    type=['csv'],
    help="File should contain a 'Case #' column with format like '23CV5681 (12844)'"
)

# Display sample format
with st.expander("📋 Expected Case Number Format"):
    st.code("Examples:\n23CV5681 (12844)\n24CV1234 (56789)\n25CV9876 (11111)")
    st.markdown("**Note:** Numbers in brackets () will be ignored")

# Sample CSV download
if st.button("📥 Download Sample CSV"):
    sample_data = {
        'Case #': ['23CV5681 (12844)', '24CV1234 (56789)', '25CV9876 (11111)'],
        'Property Address': ['123 Main St, Columbus, OH', '456 Oak Ave, Dublin, OH', '789 Pine Rd, Westerville, OH']
    }
    sample_df = pd.DataFrame(sample_data)
    st.download_button(
        label="Download Sample CSV",
        data=sample_df.to_csv(index=False),
        file_name="sample_cases.csv",
        mime="text/csv"
    )

if uploaded_file is not None:
    try:
        # Load the CSV file
        df = pd.read_csv(uploaded_file)
        st.success(f"✅ File uploaded successfully! Found {len(df)} rows")
        
        # Check if 'Case #' column exists
        if 'Case #' not in df.columns:
            st.error("❌ Error: 'Case #' column not found in the uploaded file")
            st.write("Available columns:", list(df.columns))
        else:
            # Display preview of the data
            st.subheader("📊 Data Preview")
            st.dataframe(df.head(), use_container_width=True)
            
            # Parse and validate case numbers
            valid_cases = []
            invalid_cases = []
            
            for idx, case_num in enumerate(df['Case #']):
                if pd.notna(case_num):
                    parsed = parse_case_number(str(case_num))
                    if parsed:
                        valid_cases.append((idx, case_num, parsed))
                    else:
                        invalid_cases.append((idx, case_num))
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Valid Case Numbers", len(valid_cases))
            with col2:
                st.metric("Invalid Case Numbers", len(invalid_cases))
            
            if invalid_cases:
                with st.expander("⚠️ Invalid Case Numbers"):
                    for idx, case_num in invalid_cases:
                        st.write(f"Row {idx + 1}: {case_num}")
            
            # Processing options
            st.subheader("🔧 Processing Options")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                headless_mode = st.checkbox("Run in headless mode", value=True, 
                                          help="Hide browser window during processing")
            with col2:
                delay_between_requests = st.slider("Delay between requests (seconds)", 
                                                 min_value=1, max_value=5, value=2,
                                                 help="Shorter delays = faster processing")
            with col3:
                st.info("⚡ **Speed Mode Enabled**\n- Max 45 seconds per case\n- Optimized timeouts\n- Quick navigation")
            
            # Processing summary
            estimated_time = len(valid_cases) * 0.75  # Estimate 45 seconds average per case
            st.info(f"📊 **Processing Summary**: {len(valid_cases)} cases • Estimated time: {estimated_time:.1f} minutes")
            
            # Start processing button
            if st.button("🚀 Start Fetching Attorney Data", type="primary"):
                if valid_cases:
                    # Setup progress tracking
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results_container = st.empty()
                    
                    # Initialize results DataFrame
                    results_df = df.copy()
                    
                    # Add new columns for attorney data
                    attorney_columns = [
                        'attorney_name', 'attorney_firm', 'attorney_address', 'attorney_phone',
                        'service_type', 'service_date', 'certified_mail_no', 'defendant_name',
                        'defendant_address', 'service_status', 'main_defendant', 'all_defendants',
                        'defendant_count', 'service_match', 'extraction_status'
                    ]
                    
                    for col in attorney_columns:
                        results_df[col] = ''
                    
                    # Setup browser
                    try:
                        with st.spinner("🔧 Starting browser..."):
                            driver = setup_browser(headless_mode)
                        
                        with st.spinner("🌐 Handling court website disclaimer..."):
                            if not handle_disclaimer(driver):
                                st.error("❌ Failed to handle disclaimer page. Please try again.")
                                driver.quit()
                            else:
                                st.success("✅ Successfully connected to court website")
                                
                                # Process each valid case
                                successful_extractions = 0
                                failed_extractions = 0
                            
                            for i, (row_idx, case_num, parsed_case) in enumerate(valid_cases):
                                case_start_time = time.time()
                                MAX_CASE_TIME = 45  # Maximum 45 seconds per case
                                
                                # Update progress
                                progress = (i + 1) / len(valid_cases)
                                progress_bar.progress(progress)
                                status_text.text(f"⏳ Processing {i + 1}/{len(valid_cases)}: {case_num}")
                                
                                # Process with timeout protection
                                attorney_data = None
                                search_success = False
                                
                                print(f"\n🔍 Case {i+1}/{len(valid_cases)}: {case_num}")
                                
                                # Single attempt with timeout protection
                                try:
                                    # Check overall timeout
                                    if time.time() - case_start_time > MAX_CASE_TIME:
                                        print(f"⏰ Case timeout exceeded")
                                        raise TimeoutException("Case processing timeout")
                                    
                                    status_text.text(f"🔍 {i + 1}/{len(valid_cases)}: Filling search form...")
                                    
                                    # Fill search form (quick)
                                    if fill_search_form(driver, parsed_case['year'], 
                                                      parsed_case['case_type'], parsed_case['sequence']):
                                        
                                        status_text.text(f"📊 {i + 1}/{len(valid_cases)}: Extracting data...")
                                        
                                        # Extract attorney data (with internal timeout)
                                        attorney_data = extract_attorney_data(driver)
                                        search_success = True
                                        
                                        elapsed = time.time() - case_start_time
                                        print(f"✅ Completed in {elapsed:.1f}s: {attorney_data.get('extraction_status', 'Unknown')}")
                                    else:
                                        print(f"❌ Search form failed")
                                        attorney_data = {
                                            'extraction_status': 'Search Form Failed'
                                        }
                                        
                                except Exception as e:
                                    elapsed = time.time() - case_start_time
                                    print(f"❌ Case error after {elapsed:.1f}s: {e}")
                                    attorney_data = {
                                        'extraction_status': f'Error: {str(e)}'
                                    }
                                
                                # Ensure we have attorney_data
                                if not attorney_data:
                                    attorney_data = {
                                        'attorney_name': '',
                                        'attorney_firm': '',
                                        'attorney_address': '',
                                        'attorney_phone': '',
                                        'service_type': '',
                                        'service_date': '',
                                        'certified_mail_no': '',
                                        'defendant_name': '',
                                        'defendant_address': '',
                                        'service_status': '',
                                        'main_defendant': '',
                                        'all_defendants': '',
                                        'defendant_count': 0,
                                        'service_match': '',
                                        'extraction_status': 'Failed - No Data'
                                    }
                                
                                # Update results DataFrame
                                for col in attorney_columns:
                                    results_df.loc[row_idx, col] = attorney_data.get(col, '')
                                
                                # Track success/failure
                                if attorney_data.get('extraction_status') == 'Found':
                                    successful_extractions += 1
                                else:
                                    failed_extractions += 1
                                
                                # Update display quickly
                                with results_container.container():
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("Processed", i + 1)
                                    with col2:
                                        st.metric("Successful", successful_extractions)
                                    with col3:
                                        st.metric("Failed", failed_extractions)
                                    
                                    # Show recent results
                                    if i >= 0:
                                        st.subheader("Recent Results")
                                        display_cols = ['Case #', 'main_defendant', 'attorney_name', 'service_match', 'extraction_status']
                                        recent_results = results_df.iloc[max(0, i-2):i+1][display_cols]
                                        st.dataframe(recent_results, use_container_width=True)
                                
                                # Quick navigation back for next case
                                if i < len(valid_cases) - 1:
                                    try:
                                        status_text.text(f"🔄 Preparing for next case...")
                                        driver.back()
                                        time.sleep(1)
                                        
                                        # Quick check if we're back on search form
                                        try:
                                            WebDriverWait(driver, 3).until(
                                                EC.presence_of_element_located((By.NAME, "caseYear"))
                                            )
                                        except:
                                            # Quick disclaimer re-handle if needed
                                            handle_disclaimer(driver)
                                    except:
                                        pass  # Continue anyway
                                    
                                    # Brief pause between cases
                                    time.sleep(max(1, delay_between_requests // 2))
                            
                            # Final results
                            progress_bar.progress(1.0)
                            status_text.text("✅ Processing completed!")
                            
                            st.success(f"🎉 Processing completed! Successful: {successful_extractions}, Failed: {failed_extractions}")
                            
                            # Display final results
                            st.subheader("📊 Final Results")
                            st.dataframe(results_df, use_container_width=True)
                            
                            # Download button for enhanced CSV
                            csv_data = results_df.to_csv(index=False)
                            st.download_button(
                                label="📥 Download Enhanced CSV with Attorney Data",
                                data=csv_data,
                                file_name=f"attorney_data_enhanced_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                type="primary"
                            )
                    
                    except Exception as e:
                        st.error(f"❌ Error during processing: {str(e)}")
                    
                    finally:
                        # Always close the browser
                        try:
                            driver.quit()
                        except:
                            pass
                else:
                    st.error("No valid case numbers found to process")
    
    except Exception as e:
        st.error(f"❌ Error reading CSV file: {str(e)}")
else:
    st.info("👆 Please upload a CSV file to get started")

# Add footer
st.markdown("---")
st.markdown("Made with ❤️ using Streamlit | Franklin County Court Data Fetcher")