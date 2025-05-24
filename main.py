from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
import os
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from serpapi import GoogleSearch
import google.generativeai as genai
from dotenv import load_dotenv, find_dotenv
import json

# === Load environment variables safely ===
env_path = find_dotenv()
if env_path:
    print(f"Loading .env file at: {env_path}")
    load_dotenv(env_path)
else:
    print("No .env file found, using environment variables directly")

print(f".env file exists: {os.path.exists('.env')}")
if os.path.exists('.env'):
    print(f".env file size: {os.path.getsize('.env')} bytes")
else:
    print(".env file not found, skipping size check.")

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")

# Debug prints for environment variables
print("\nEnvironment Variables Check:")
print(f"SERPAPI_KEY exists: {'SERPAPI_KEY' in os.environ}")
print(f"SERPAPI_KEY value: {SERPAPI_KEY}")
print(f"SERPAPI_KEY length: {len(SERPAPI_KEY) if SERPAPI_KEY else 0}")
print(f"GEMINI_KEY exists: {'GEMINI_KEY' in os.environ}")
print(f"GEMINI_KEY value: {GEMINI_KEY}")
print(f"GEMINI_KEY length: {len(GEMINI_KEY) if GEMINI_KEY else 0}\n")

# === Configure Gemini ===
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# === Flask App Setup ===
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Required for flashing messages

# Ensure static directory exists
os.makedirs('static', exist_ok=True)

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join('static', filename), as_attachment=True)

@app.route('/results')
def results():
    return render_template("results.html")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            location = request.form.get('location')
            search_term = request.form.get('search_term')
            print(f"Initial search parameters - Location: {location}, Business Type: {search_term}")  # Debug print

            if not location or not search_term:
                flash('Please provide both location and search term', 'error')
                return redirect(url_for('index'))

            # Format the location for the API
            location = location.strip()
            if ',' in location:
                city, state = [part.strip() for part in location.split(',', 1)]
                location = f"{city}, {state}"

            # First, use Gemini to refine the search query
            try:
                prompt = f"""Given a business type '{search_term}' in location '{location}', 
                generate a refined search query that would work well with Google Maps search. 
                The query should be specific and likely to return relevant business results.
                Return ONLY the search query, nothing else."""
                
                print("Sending prompt to Gemini...")  # Debug print
                response = model.generate_content(prompt)
                refined_query = response.text.strip()
                print(f"Gemini refined query: {refined_query}")  # Debug print
                
                if not refined_query:
                    refined_query = f"{search_term} in {location}"
            except Exception as e:
                print(f"Error with Gemini API: {str(e)}")  # Debug print
                refined_query = f"{search_term} in {location}"
                flash('Note: Using original search query due to Gemini API issue', 'warning')

            # Now use the refined query with SerpAPI
            params = {
                "engine": "google_maps",
                "q": refined_query,
                "type": "search",
                "api_key": SERPAPI_KEY,
                "hl": "en",
                "gl": "us"
            }

            print("Making SerpAPI request...")  # Debug print
            print(f"Search params: {params}")  # Debug print
            
            try:
                search = GoogleSearch(params)
                results = search.get_dict()  # directly get dict, no JSON parsing needed
                print(f"Parsed API Response: {results}")  # Debug print
            except Exception as e:
                print(f"API Request Error: {str(e)}")
                flash('Error connecting to search service. Please try again.', 'error')
                return redirect(url_for('index'))

            businesses = []

            if not results.get("local_results"):
                print("No local results found")  # Debug print
                flash('No businesses found for the given search criteria. Try a different location or search term.', 'error')
                return redirect(url_for('index'))

            print(f"Found {len(results.get('local_results', []))} businesses")  # Debug print

            for biz in results.get("local_results", []):
                name = biz.get("title", "N/A")
                category = biz.get("type", "N/A")
                address = biz.get("address", "N/A")
                phone = biz.get("phone", "N/A")
                website = biz.get("website", "N/A")

                print(f"Processing business: {name}")  # Debug print

                desc = "N/A"
                if name and category and name != "N/A" and category != "N/A":
                    try:
                        prompt = f"What services does this business likely offer?\nBusiness: {name}\nCategory: {category}"
                        response = model.generate_content(prompt)
                        desc = response.text.strip()
                    except Exception as e:
                        print(f"Error generating description: {str(e)}")

                email = "N/A"
                if website and website != "N/A":
                    try:
                        page = requests.get(website, timeout=5).text
                        soup = BeautifulSoup(page, "html.parser")
                        text = soup.get_text()
                        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
                        if emails:
                            email = emails[0]
                    except Exception as e:
                        print(f"Error extracting email: {str(e)}")

                business_data = {
                    "Name": name,
                    "Category": category,
                    "Address": address,
                    "Phone": phone,
                    "Website": website,
                    "Email": email,
                    "Services (Gemini)": desc
                }
                print(f"Added business: {business_data}")  # Debug print
                businesses.append(business_data)

            if not businesses:
                print("No valid businesses found")  # Debug print
                flash('No valid business data found. Try a different location or search term.', 'error')
                return redirect(url_for('index'))

            print(f"Total businesses processed: {len(businesses)}")  # Debug print

            # Save to CSV
            df = pd.DataFrame(businesses)
            output_file = "businesses_output.csv"
            output_path = os.path.join('static', output_file)
            df.to_csv(output_path, index=False)
            print(f"Saved CSV to: {output_path}")  # Debug print

            # Store businesses in session for results page
            session['businesses'] = businesses
            session['download_link'] = url_for('download_file', filename=output_file)

            # Redirect to results page
            return redirect(url_for('results'))

        except Exception as e:
            print(f"Error in main processing: {str(e)}")  # Debug print
            flash(f'An error occurred: {str(e)}. Please try again.', 'error')
            return redirect(url_for('index'))

    return render_template("index.html")

if __name__ == '__main__':
    app.run(debug=True)
