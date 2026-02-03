# Neo4j & LanceDB Setup Guide (User-Space / No Docker)

**Version:** 1.1 (Includes APOC)  
**Server:** Ubuntu (via SSH)  
**Client:** Local Laptop (VS Code / Terminal)  

## Context

This setup runs entirely in user-space using Conda and portable binaries.  
It requires **NO root access (sudo)** and **NO Docker**.

---

## Part 1: Server-Side Installation

### 1. Create & Configure Conda Environment

We use Conda to isolate the Python libraries and the Java runtime.

```bash
# Create environment (Python 3.10 recommended for LanceDB)
conda create -n graph_env python=3.10 -y

# Activate the environment
conda activate graph_env
```

### 2. Install Java 17 (Required for Neo4j 5.x)

Neo4j requires Java 17. We install it via Conda to avoid system conflicts.

```bash
conda install -c conda-forge openjdk=17 -y

# Verify installation (Must say "openjdk 17...")
java -version
```

### 3. Download & Extract Neo4j (Tarball Method)

Since we aren't using apt/docker, we download the portable Linux version.

```bash
# Download Neo4j Community Edition 5.18.0
wget [https://dist.neo4j.org/neo4j-community-5.18.0-unix.tar.gz](https://dist.neo4j.org/neo4j-community-5.18.0-unix.tar.gz) -O neo4j.tar.gz

# Extract it
tar -xf neo4j.tar.gz

# Rename folder for easier typing
mv neo4j-community-5.18.0 neo4j_home

# Clean up the zip file
rm neo4j.tar.gz
```

### 4. Install APOC Plugin (Essential for Data Import)

APOC (Awesome Procedures on Cypher) is a standard utility library. In Neo4j 5, we must download the JAR manually and configure it.

```bash
# A. Download the APOC Core JAR into the plugins folder
cd neo4j_home/plugins
wget [https://github.com/neo4j/apoc/releases/download/5.18.0/apoc-5.18.0-core.jar](https://github.com/neo4j/apoc/releases/download/5.18.0/apoc-5.18.0-core.jar)
cd ../..

# B. Enable APOC in the configuration
# We need to allow "unrestricted" access for APOC to work correctly.
# Run this command to append the setting to your config file:
echo "dbms.security.procedures.unrestricted=apoc.*" >> neo4j_home/conf/neo4j.conf
```

### 5. Install Python Libraries

Install the embedded vector database (LanceDB) and the Neo4j driver.

```bash
pip install lancedb neo4j pandas
```

### 6. Start the Server

We must set `JAVA_HOME` so Neo4j finds the Conda-installed Java.

```bash
# Set Java Home to current Conda env
export JAVA_HOME=$CONDA_PREFIX

# Start Neo4j in the background
./neo4j_home/bin/neo4j start

# Check status (Wait 10-20s for it to fully start)
./neo4j_home/bin/neo4j status
```

## Part 2: Client-Side Access (Laptop)

Neo4j runs on ports 7474 (HTTP) and 7687 (Bolt). You need to forward these from the server to your laptop

### Option A: Automatic (Via VS Code)

1. If you are using VS Code Remote-SSH, open the "Ports" panel (Ctrl+J -> Ports).
2. Look for 7474 and 7687.
3. If they are listed, VS Code is already forwarding them.
    - Note the "Local Address" column!
    - If it says `localhost:7474`, you are good.
    - If it says `localhost:54321`, use THAT port instead.

## Part 3: Verification & Testing

### 1. Web Browser

Go to: `http://localhost:7474`
    - Connect URL: neo4j://localhost:7687
    - User/Pass: neo4j / neo4j (Change password when prompted)
    - TEST APOC: In the top bar, type:

```Cypher
RETURN apoc.version();
```

### 2. Python Script (Run on Server)

Create a file verify_stack.py and run python verify_stack.py.

```Python
import lancedb
from neo4j import GraphDatabase

# --- CONFIG ---
# Update password below
NEO4J_AUTH = ("neo4j", "your_new_password") 

print("--- 1. Testing LanceDB ---")
ldb = lancedb.connect("./lancedb_data")
tbl = ldb.create_table("test", [{"vector": [1.0, 0.0], "id": 1}], mode="overwrite")
print("LanceDB OK: Table created.")

print("\n--- 2. Testing Neo4j & APOC ---")
with GraphDatabase.driver("bolt://localhost:7687", auth=NEO4J_AUTH) as driver:
    driver.verify_connectivity()
    with driver.session() as session:
        # Check if APOC is loaded via Python
        result = session.run("RETURN apoc.version() AS ver").single()
        print(f"Neo4j OK. APOC Version: {result['ver']}")
```

## Part 4: Maintenance Cheatsheet

Stop Server:

```bash
./neo4j_home/bin/neo4j stop
```

Start Server:

```bash
export JAVA_HOME=$CONDA_PREFIX
./neo4j_home/bin/neo4j start
```

View Logs (If it fails to start):

```bash
cat neo4j_home/logs/neo4j.log
```

Reset Password (If you forget it):

```bash
# Stop server first
./neo4j_home/bin/neo4j stop
# Remove auth file
rm neo4j_home/data/dbms/auth
# Start again (Default becomes neo4j/neo4j)
./neo4j_home/bin/neo4j start
```
