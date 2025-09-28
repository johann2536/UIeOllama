// ...existing code...
function renderList() {
    songList.innerHTML = "";

    const list = (folder === "Custom") 
        ? customSongs 
        : songs.map(f => ({
            file: f, 
            name: f.replace(/\.mp3$/i, ""),
            folder: folder
        }));

    if (list.length === 0) {
        const li = document.createElement("li");
        li.textContent = <?php echo json_encode($t['no_songs']); ?>;
        li.style.textAlign = "center";
        li.style.color = "#666";
        songList.appendChild(li);
        return;
    }

    list.forEach((song, index) => {
        const li = document.createElement("li");
        li.dataset.index = index;
        li.dataset.file = song.file;

        const span = document.createElement("span");
        span.textContent = song.name;
        span.style.flex = "1";
        li.appendChild(span);

        const buttonContainer = document.createElement("div");
        buttonContainer.style.display = "flex";
        buttonContainer.style.gap = "4px";

        if (folder === "Custom") {
            const removeBtn = createActionButton("❌", "removeBtn", (e) => {
                e.stopPropagation();
                if (confirm("Remove this song from custom playlist?")) {
                    customSongs.splice(index, 1);
                    try {
                        localStorage.setItem("customPlaylist", JSON.stringify(customSongs));
                    } catch (e) {
                        console.error("Failed to save custom playlist:", e);
                    }
                    renderList();
                }
            });
            // Optionally add download button for custom playlist
            const downloadBtn = createActionButton("⬇", "downloadBtn", (e) => {
                e.stopPropagation();
                const link = document.createElement("a");
                link.href = `music/${encodeURIComponent(song.folder)}/${encodeURIComponent(song.file)}`;
                link.download = song.file;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            });
            buttonContainer.appendChild(removeBtn);
            buttonContainer.appendChild(downloadBtn);
        } else {
            const addBtn = createActionButton("➕", "addBtn", (e) => {
                e.stopPropagation();
                const existingSong = customSongs.find(s => 
                    s.file === song.file && s.folder === song.folder
                );
                
                if (existingSong) {
                    alert("Song already in custom playlist!");
                    return;
                }
                
                customSongs.push({
                    file: song.file,
                    name: song.name,
                    folder: song.folder
                });
                
                try {
                    localStorage.setItem("customPlaylist", JSON.stringify(customSongs));
                    alert("Added to Custom Playlist!");
                } catch (e) {
                    console.error("Failed to save custom playlist:", e);
                    alert("Failed to add to playlist. Storage may be full.");
                }
            });

            const downloadBtn = createActionButton("⬇", "downloadBtn", (e) => {
                e.stopPropagation();
                const link = document.createElement("a");
                link.href = `music/${encodeURIComponent(song.folder)}/${encodeURIComponent(song.file)}`;
                link.download = song.file;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            });

            buttonContainer.appendChild(addBtn);
            buttonContainer.appendChild(downloadBtn);
        }

        li.appendChild(buttonContainer);
        li.onclick = () => setIndex(index, true);
        songList.appendChild(li);
    });
}

function setIndex(index, playNow = false) {
    const list = (folder === "Custom") 
        ? customSongs 
        : songs.map(f => ({
            file: f, 
            name: f.replace(/\.mp3$/i, ""),
            folder: folder
        }));

    if (!list[index]) {
        audio.src = "";
        nowPlaying.textContent = `${translations.nowPlaying}: —`;
        [...songList.children].forEach(li => li.classList.remove('active'));
        return;
    }

    const song = list[index];
    const src = `music/${encodeURIComponent(song.folder)}/${encodeURIComponent(song.file)}`;

    audio.src = src;
    audio.load();
    current = index;

    // Update active state
    [...songList.children].forEach(li => li.classList.remove('active'));
    const activeLi = songList.children[index];
    if (activeLi) {
        activeLi.classList.add('active');
        activeLi.scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    nowPlaying.textContent = `${translations.nowPlaying}: ${song.name}`;

    if (playNow) {
        audio.play().catch(e => {
            console.warn("Autoplay prevented:", e);
        });
    }
}
// ...existing code...