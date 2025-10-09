const fs = require('fs-extra');
const path = require('path');
const { spawnSync, exec } = require('child_process');
const os = require('os');
const { applyColorToGlb } = require('./objConverter');
const { NodeIO } = require('@gltf-transform/core');

// Helper function to convert GLTF to GLB using gltf-transform
async function convertGltfToGlb(gltfPath, glbPath) {
    const io = new NodeIO();
    try {
        console.log(`[convertGltfToGlb] Reading GLTF from: ${gltfPath}`);
        const document = await io.read(gltfPath); // Read the GLTF file (handles .bin automatically)

        console.log(`[convertGltfToGlb] Writing GLB to: ${glbPath}`);
        await io.write(glbPath, document); // Write the document as GLB

        console.log(`[convertGltfToGlb] Successfully converted GLTF to GLB: ${gltfPath} -> ${glbPath}`);
        return true; // Indicate success
    } catch (error) {
        console.error(`[convertGltfToGlb] Error converting GLTF to GLB (${gltfPath}): ${error.message}`);
        console.error(error.stack); // Log stack for more details
        return false; // Indicate failure
    }
}

// Helper function to update texture paths in GLTF JSON
function updateTexturePaths(gltfJson, texturesDir) {
    // Implementation depends on your texture handling logic
    // This is a placeholder - adapt it to your needs
    if (gltfJson.images) {
        gltfJson.images.forEach(image => {
            if (image.uri && !image.uri.startsWith('data:')) {
                const textureName = path.basename(image.uri);
                // Assuming textures are copied to a 'textures' subdirectory relative to the GLB
                image.uri = `textures/${textureName}`;
            }
        });
    }
    if (gltfJson.textures) {
        // Potentially update texture source indices if images array was modified
    }
    // Add other necessary updates for materials, etc.
}

async function convertFbxToGlb(fbxFilePath, outputDir, color) {
    const tempDir = path.join(os.tmpdir(), `fbx2glb_${Date.now()}`);
    const texturesDir = path.join(outputDir, 'textures'); // Define textures dir relative to final output
    let finalGlbPath = null;

    try {
        // Create directories
        fs.mkdirSync(tempDir, { recursive: true });
        console.log(`Created temporary directory: ${tempDir}`);
        fs.mkdirSync(texturesDir, { recursive: true });
        console.log(`Created textures directory: ${texturesDir}`);

        // Run FBX2glTF
        const fbx2glTFPath = path.join(__dirname, '../bin/FBX2glTF.exe');
        if (!fs.existsSync(fbx2glTFPath)) {
            throw new Error(`FBX2glTF executable not found at: ${fbx2glTFPath}`);
        }
        const fbx2glTFCommand = `"${fbx2glTFPath}" -i "${fbxFilePath}" -o "${tempDir}"`;
        console.log(`Running command: ${fbx2glTFCommand}`);
        try {
            const { stdout, stderr } = await new Promise((resolve, reject) => {
                exec(fbx2glTFCommand, (error, stdout, stderr) => {
                    if (error) {
                        console.error(`FBX2glTF execution error: ${stderr || error.message}`);
                        // Attempt to continue even if there are non-fatal errors in stderr
                        // reject(error);
                        // return;
                    }
                    resolve({ stdout, stderr });
                });
            });
            console.log(`FBX2glTF output: ${stdout}`);
            if (stderr && stderr.toLowerCase().includes('error')) {
                // Log significant errors from stderr but maybe don't halt execution unless critical
                console.error(`FBX2glTF reported errors: ${stderr}`);
            }
        } catch (execError) {
            console.error(`Error executing FBX2glTF process: ${execError.message}`);
            throw execError; // Re-throw if the process itself failed
        }

        // Find the output file (_out directory)
        const outDir = path.join(tempDir + '_out');
        if (!fs.existsSync(outDir)) {
            console.error(`FBX2glTF output directory not found: ${outDir}`);
            // Check if files were created directly in tempDir instead
            const filesInTemp = fs.readdirSync(tempDir);
            const gltfInTemp = filesInTemp.find(file => file.endsWith('.gltf'));
            const glbInTemp = filesInTemp.find(file => file.endsWith('.glb'));
            if (!gltfInTemp && !glbInTemp) {
                throw new Error('FBX conversion failed: No output directory or files found.');
            } else {
                console.warn(`Output files found directly in ${tempDir}, not in expected _out subdir.`);
                // Adjust outDir if needed, or handle files directly from tempDir
                // For now, let's assume _out is the standard
                throw new Error('FBX conversion failed: Output directory structure unexpected.');
            }
        }

        console.log(`Found FBX2glTF output directory: ${outDir}`);
        const filesInOutDir = fs.readdirSync(outDir);
        console.log(`Files in output directory: ${filesInOutDir.join(', ')}`);

        // Find potential output files
        const tempGlbFile = filesInOutDir.find(file => file.endsWith('.glb'));
        const tempGltfFile = filesInOutDir.find(file => file.endsWith('.gltf'));

        finalGlbPath = path.join(outputDir, `${path.basename(fbxFilePath, '.fbx')}.glb`);

        if (tempGlbFile) {
            // FBX2glTF produced a GLB directly
            const sourceGlbPath = path.join(outDir, tempGlbFile);
            console.log(`Found GLB file directly from FBX2glTF: ${sourceGlbPath}. Copying to final destination.`);
            fs.copyFileSync(sourceGlbPath, finalGlbPath);
        } else if (tempGltfFile) {
            // FBX2glTF produced GLTF + BIN, need to convert
            const sourceGltfPath = path.join(outDir, tempGltfFile);
            console.log(`Found GLTF file: ${sourceGltfPath}. Processing and converting to GLB.`);

            // --- Optional texture path update logic can remain commented out or removed if not used ---
            // const gltfJson = JSON.parse(fs.readFileSync(sourceGltfPath, 'utf8'));
            // updateTexturePaths(gltfJson, texturesDir); // Assuming texturesDir is defined earlier
            // fs.writeFileSync(sourceGltfPath, JSON.stringify(gltfJson));
            // console.log(`Updated texture paths in ${sourceGltfPath}`);
            // --- End Optional ---

            // Convert the GLTF to the final GLB path using the helper function
            if (!(await convertGltfToGlb(sourceGltfPath, finalGlbPath))) { // Await the async function
                // convertGltfToGlb already logs errors, maybe throw specific error here
                throw new Error(`Failed to convert GLTF to GLB: ${sourceGltfPath}`);
            }
            console.log(`Converted GLTF to final GLB: ${finalGlbPath}`);
        } else {
            // Neither GLB nor GLTF found
            throw new Error('FBX conversion failed: No GLTF or GLB file found in output directory.');
        }

        // Apply color if specified
        if (finalGlbPath && color && color.length === 3 && (color[0] !== 1 || color[1] !== 1 || color[2] !== 1)) {
            console.log(`Applying color [${color.join(', ')}] to ${finalGlbPath}`);
            try {
                await applyColorToGlb(finalGlbPath, color[0], color[1], color[2]);
                console.log(`Color applied successfully to FBX-converted GLB: ${finalGlbPath}`);
            } catch (colorError) {
                // Check if the error is likely due to a corrupt/unreadable GLB from FBX2glTF
                const errorMessage = colorError.message || '';
                if (errorMessage.includes('JSON') || errorMessage.includes('gltf-transform') || errorMessage.includes('GLB')) {
                    console.warn(`[FBX Conversion Warning] Failed to read/process the GLB file generated by FBX2glTF for color application: ${finalGlbPath}. The GLB file might be corrupted or incompatible. Color was not applied. Error: ${errorMessage}`);
                    // Do not re-throw, allow the process to continue as conversion itself (by FBX2glTF) technically finished.
                } else {
                    // Log other unexpected errors during color application
                    console.error(`Error applying color to FBX-converted GLB ${finalGlbPath}:`, colorError);
                    // Optionally re-throw for unknown errors if needed, but currently handled by outer try/catch in route.
                }
            }
        } else {
            console.log('Default white color selected for FBX, skipping color application.');
        }

        return finalGlbPath;

    } catch (error) {
        console.error(`Error in convertFbxToGlb: ${error.message}`);
        // Log the stack trace for more details
        console.error(error.stack);
        throw error; // Re-throw the error to be caught by the calling route
    } finally {
        // Clean up the temporary directory
        if (fs.existsSync(tempDir)) {
            fs.removeSync(tempDir);
            console.log(`Removed temporary directory: ${tempDir}`);
        }
        // Clean up the _out directory if it exists separately
        const outDir = path.join(tempDir + '_out');
        if (fs.existsSync(outDir)) {
            fs.removeSync(outDir);
            console.log(`Removed temporary _out directory: ${outDir}`);
        }
    }
}

module.exports = { convertFbxToGlb };
