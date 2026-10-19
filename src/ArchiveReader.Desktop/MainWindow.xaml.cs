using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Channels;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using Microsoft.Win32;

namespace ArchiveReader;

public record PageItem(string Id, string Doc, int Num, string Name, string Path, string State)
{
    public string Label => $"{Name}\n{Localizer.Text("Стор.")} {Num + 1} · {Localizer.Text(State)}";
}
public record RecordItem(JsonObject Data)
{
    public string Label => Data["id"]==null && Data["kind"]==null ? Data["person"]?.ToString() ?? "" : $"{Data["number"]} {Data["person"]} · {Localizer.Text(Data["kind"]?.ToString() ?? "")}";
}
public record LineItem(int Index, JsonObject Data)
{
    public string Label => $"{(Data["review_flags"] is JsonArray flags && flags.Count>0 ? "⚠ " : "")}{(Data["confidence"] is JsonNode c ? (c.GetValue<double>() * 100).ToString("F0") + "%" : "—")} · {Data["corrected"] ?? Data["text"]}";
}

public partial class MainWindow : Window
{
    static readonly string[] KindKeys = ["Інші записи та примітки", "Народження", "Шлюби", "Смерті", "Нерозбірливі записи"];
    static string T(string text) => Localizer.Text(text);
    static string F(string text, params object?[] args) => Localizer.Format(text,args);
    readonly string root = Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA") ?? System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ArchiveReader");
    readonly string python = PythonRuntime.Resolve();
    PageItem? current;
    string? recordId;
    bool loading = true, dirty, busy, switching;
    int generation, workers = 1;
    readonly SemaphoreSlim saveLock = new(1,1);
    CancellationTokenSource? work;
    List<PageItem> allPages = []; // Only the current bounded metadata window.
    int pageOffset,pageTotal;string? pageSnapshot;
    Point? regionStart;

    public MainWindow()
    {
        InitializeComponent();
        Closed+=(_,_)=>modelSession?.Dispose();
        Loaded += async (_, _) => await Guard(async () =>
        {
            var arguments=Environment.GetCommandLineArgs();
            var importIndex=Array.IndexOf(arguments,"--smoke-import");
            if(importIndex >= 0)
            {
                if(importIndex+1 >= arguments.Length) throw new ArgumentException("--smoke-import requires a file path");
                var imported=await Call("import_file",new() { ["path"]=arguments[importIndex+1] });
                Directory.CreateDirectory(root);
                File.WriteAllText(System.IO.Path.Combine(root,"smoke-import.json"),imported.ToJsonString());
                closing=true; Close(); return;
            }
            // One UI instance per local library prevents recovery racing with live workers.
            await Call("recover");
            var profile = await Call("profile");
            workers = profile["workers"]!.GetValue<int>();
            var settings = await Call("settings");
            OcrEngine.SelectedIndex = settings["engine"]?.ToString() switch {"tesseract"=>1,"trocr"=>2,"paddle"=>3,_=>0};
            OcrPath.Text = settings["executable"]?.ToString() ?? Environment.GetEnvironmentVariable("ARCHIVEREADER_KRAKEN") ?? "kraken";
            ModelPath.Text = settings["model"]?.ToString() ?? Environment.GetEnvironmentVariable("ARCHIVEREADER_MODEL") ?? "";
            SegmentationPath.Text = settings["segmentation"]?.ToString() ?? "";
            Languages.Text = settings["languages"]?.ToString() ?? "eng";
            InterfaceLanguage.SelectedIndex = Math.Max(0, Array.IndexOf(new[] { "uk", "en", "pl", "cs" }, Environment.GetEnvironmentVariable("ARCHIVEREADER_LANGUAGE") ?? settings["uiLanguage"]?.ToString() ?? "uk"));
            Localizer.Apply(this, ((ComboBoxItem)InterfaceLanguage.SelectedItem).Tag.ToString()!);
            await RefreshPages();
            Status.Text = F("Готово • CPU: {0} • RAM: {1} ГБ • OCR-процесів: {2} • Дані: {3}",profile["cpu"],profile["ramGB"],workers,root);
            loading = false;
            await InitializeBackups();
            if (Environment.GetCommandLineArgs().Contains("--smoke-test"))
            {
                if(Environment.GetCommandLineArgs().Contains("--smoke-model-catalog"))
                {
                    var catalog=new ModelCatalogWindow(python){Owner=this};
                    catalog.ContentRendered+=(_,_)=>{var image=new RenderTargetBitmap((int)catalog.ActualWidth,(int)catalog.ActualHeight,96,96,PixelFormats.Pbgra32);image.Render(catalog);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using(var output=File.Create(System.IO.Path.Combine(root,"model-catalog.png")))encoder.Save(output);catalog.Close();};
                    catalog.ShowDialog();
                }
                if (allPages.Count > 0) { current=allPages[0]; await LoadPage(current); }
                if(Environment.GetCommandLineArgs().Contains("--smoke-recognition-workflow")&&current!=null)
                {
                    var workflow=new RecognitionWorkflowWindow(current.Id,"paddle",Call){Owner=this};
                    workflow.ContentRendered+=async(_,_)=>{await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.ApplicationIdle);await Task.Delay(700);var image=new RenderTargetBitmap((int)workflow.ActualWidth,(int)workflow.ActualHeight,96,96,PixelFormats.Pbgra32);image.Render(workflow);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using(var output=File.Create(System.IO.Path.Combine(root,"recognition-workflow.png")))encoder.Save(output);workflow.Close();};
                    workflow.ShowDialog();
                }
                if(Environment.GetCommandLineArgs().Contains("--smoke-tutor") && current!=null)new TutorWindow(current.Id,ModelPath.Text,Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-agents") && current!=null)new AgentWindow(current.Id,Call,ModelPath.Text){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-corpus"))new CorpusWindow(current?.Id,ModelPath.Text,Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-facts") && current!=null && Records.Items.Count>0)new FactReviewWindow(current.Id,((RecordItem)Records.Items[0]).Data["id"]!.ToString(),Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-session"))
                {
                    var first=await Call("session_status");var second=await Call("session_status");
                    if(first["pid"]!.ToString()!=second["pid"]!.ToString())throw new Exception("Persistent worker was not reused.");
                    File.WriteAllText(System.IO.Path.Combine(root,"session-smoke.json"),new JsonObject{["first"]=first.DeepClone(),["second"]=second.DeepClone()}.ToJsonString());
                }
                if(Environment.GetCommandLineArgs().Contains("--smoke-bundle"))new ResearchBundleWindow(Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-historical") && current!=null)new HistoricalReadingWindow(current.Id,Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-interchange") && current!=null)new InterchangeWindow(current.Id,Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-hub") && current!=null)new ResearchHubWindow(current.Id,Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-board"))new BoardWindow(Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap") && current!=null)
                {
                    new GenealogyWindow(current.Id,Call){Owner=this}.ShowDialog();
                    new ExtractionWindow(current.Id,"roadmap-child",Call){Owner=this}.ShowDialog();
                    new OperationsWindow(OcrSettings(),Call){Owner=this}.ShowDialog();
                    new ResearchWindow(current.Id,Call){Owner=this}.ShowDialog();
                    new BooksWindow(current.Id,OcrSettings(),Call){Owner=this}.ShowDialog();
                }
                if(Environment.GetCommandLineArgs().Contains("--smoke-shortcuts")) await SmokeShortcuts();
                if(Environment.GetCommandLineArgs().Contains("--smoke-backups")) new BackupWindow(Call){Owner=this}.ShowDialog();
                if(Environment.GetCommandLineArgs().Contains("--smoke-workbench") && current!=null)
                {
                    var workbench=new WorkbenchWindow(current,Call,ModelPath.Text) { Owner=this };
                    workbench.ShowDialog();
                }
                  if(Environment.GetCommandLineArgs().Contains("--smoke-library"))
                  { new LibraryWindow(current,Call) { Owner=this }.ShowDialog(); }
                UpdateLayout();
                var shot = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32);
                shot.Render(this);
                var png = new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(shot));
                using(var file=File.Create(System.IO.Path.Combine(root,"window.png"))) png.Save(file);
                if(Environment.GetCommandLineArgs().Contains("--smoke-roadmap")) Transcript.Text+="\nSynthetic close-save regression";
                Close();
            }
        });
    }

    PythonSession? modelSession;
    readonly object modelSessionLock=new();
    PythonSession GetModelSession(){lock(modelSessionLock)return modelSession??=new PythonSession(python,root,AppContext.BaseDirectory);}
    static readonly HashSet<string> PersistentCommands=new(){"page_review_step","recognize","batch_step","compare_regions","heldout_compare","benchmark_compare","recognize_region","tutor_compare","agent_step","corpus_compare","train_model","candidate_train_check","tutor_train","session_status"};
    async Task<JsonNode> Call(string command, JsonObject? args = null, CancellationToken token = default)
    {
        var timer=Stopwatch.StartNew();string? failure=null;
        bool persistent=PersistentCommands.Contains(command)&&Environment.GetEnvironmentVariable("ARCHIVEREADER_DISABLE_SESSION")!="1";
        try
        {
            if(persistent)return await GetModelSession().CallAsync(command,args,token);
            return await CallOnce(command,args,token);
        }
        catch(Exception ex){failure=ex.GetType().Name;throw;}
        finally{PerformanceTelemetry.Record(root,command,persistent?"persistent":"one-shot",timer.Elapsed.TotalMilliseconds,failure);}
    }
    async Task<JsonNode> CallOnce(string command, JsonObject? args = null, CancellationToken token = default)
    {
        args ??= new JsonObject(); args["command"] = command; args["root"] = root;
        var start = new ProcessStartInfo(python) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory=AppContext.BaseDirectory, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8, StandardInputEncoding = new UTF8Encoding(false) };
        start.ArgumentList.Add("-X"); start.ArgumentList.Add("utf8"); start.ArgumentList.Add("-u");
        start.ArgumentList.Add(System.IO.Path.Combine(AppContext.BaseDirectory, "engine.py"));
        start.Environment["PYTHONUTF8"] = "1";
        using var process = Process.Start(start) ?? throw new Exception(T("Не вдалося запустити Python."));
        using var registration = token.Register(() => { try { process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { } });
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        await process.StandardInput.WriteAsync(args.ToJsonString()); process.StandardInput.Close();
        await process.WaitForExitAsync(token);
        var raw = await output; var stderr = await error;
        JsonNode? result;
        try { result = JsonNode.Parse(raw); }
        catch
        {
            var diagnosticDirectory=System.IO.Path.Combine(root,"diagnostics"); Directory.CreateDirectory(diagnosticDirectory);
            var log=System.IO.Path.Combine(diagnosticDirectory,$"worker-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}.log");
            var exitCode=$"{process.ExitCode} (0x{unchecked((uint)process.ExitCode):X8})";
            await File.WriteAllTextAsync(log,$"Command: {command}\nPython: {python}\nEngine: {start.ArgumentList[^1]}\nExit: {exitCode}\nSTDERR:\n{stderr}\nSTDOUT:\n{raw}",Encoding.UTF8);
            throw new Exception(F("Рушій не повернув відповідь. Код завершення: {0}. Журнал: {1}",exitCode,log));
        }
        if (result?["ok"]?.GetValue<bool>() != true) throw new Exception(T(result?["error"]?.ToString() ?? stderr));
        return result["result"]!;
    }

    async Task Guard(Func<Task> action)
    {
        try { await action(); }
        catch (OperationCanceledException) { Status.Text = T("Обробку зупинено. Збережені результати залишилися в бібліотеці."); }
        catch (Exception e)
        {
            Status.Text = T("Помилка: ") + e.Message;
            if(Environment.GetCommandLineArgs().Any(a=>a is "--smoke-test" or "--smoke-import"))
            {
                Directory.CreateDirectory(root); File.WriteAllText(System.IO.Path.Combine(root,"smoke-error.txt"),e.ToString());
                closing=true; Application.Current.Shutdown(1); return;
            }
            MessageBox.Show(this, e.Message+(loading ? "\n\n"+T("Якщо бібліотека не відкривається, натисніть «Резервні копії» та відновіть її в нову папку.") : ""), "ArchiveReader", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    async Task RefreshPages(string? selected = null,int? offset = null,bool locateCurrent = true)
    {
        var locate=selected ?? (locateCurrent?current?.Id:null);
        var result=await Call("pages_window",new(){["query"]=SearchText.Text,["limit"]=200,["offset"]=offset ?? pageOffset,["locate"]=locate,["snapshot"]=pageSnapshot});
        if(result["locate_missing"]?.GetValue<bool>()==true && selected!=null && SearchText.Text.Length>0){SearchText.Clear();result=await Call("pages_window",new(){["limit"]=200,["locate"]=selected});}
        allPages=result["rows"]!.AsArray().Select(n=>new PageItem(n!["id"]!.ToString(),n["doc"]!.ToString(),n["num"]!.GetValue<int>(),n["display_name"]?.ToString()??n["name"]!.ToString(),n["path"]!.ToString(),n["status"]!.ToString())).ToList();
        pageOffset=result["offset"]!.GetValue<int>();pageTotal=result["total"]!.GetValue<int>();pageSnapshot=result["snapshot"]!.ToString();
        switching=true;Pages.ItemsSource=allPages;Pages.SelectedItem=allPages.FirstOrDefault(p=>p.Id==(selected??current?.Id));switching=false;
        PageRange.Text=$"{(pageTotal==0?0:pageOffset+1)}–{pageOffset+allPages.Count} / {pageTotal}";
        PreviousPages.IsEnabled=pageOffset>0;NextPages.IsEnabled=result["has_more"]!.GetValue<bool>();
    }
    async void MovePageWindow(object sender,RoutedEventArgs e)
    {
        if(switching||busy)return;PreviousPages.IsEnabled=NextPages.IsEnabled=false;
        await Guard(async()=>{await SaveCurrent();int offset=Math.Max(0,pageOffset+(ReferenceEquals(sender,NextPages)?200:-200));await RefreshPages(offset:offset,locateCurrent:false);if(allPages.FirstOrDefault() is PageItem next){current=next;recordId=null;dirty=false;switching=true;Pages.SelectedItem=next;switching=false;await LoadPage(next);}});
        PreviousPages.IsEnabled=pageOffset>0;NextPages.IsEnabled=pageOffset+allPages.Count<pageTotal;
    }

    async void Import(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        var dialog = new OpenFileDialog { Multiselect = true, Filter = T("Документи")+"|*.pdf;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp;*.gif" };
        if (dialog.ShowDialog() != true) return;
        busy = true;
        await Guard(async () =>
        {
            var failures = new List<string>(); int added = 0, duplicates = 0;
            foreach (var file in dialog.FileNames)
            {
                Status.Text = T("Імпорт: ") + System.IO.Path.GetFileName(file);
                try { var result = await Call("import_file", new() { ["path"] = file }); if (result["duplicate"]!.GetValue<bool>()) duplicates++; else added++; }
                catch (Exception ex) { failures.Add(System.IO.Path.GetFileName(file) + ": " + ex.Message); }
            }
            await RefreshPages();
            Status.Text = F("Імпортовано: {0}; дублікатів: {1}; помилок: {2}.",added,duplicates,failures.Count);
            if (failures.Count > 0) MessageBox.Show(this, string.Join("\n", failures), T("Звіт імпорту"));
        });
        busy = false;
    }

    async void SelectPage(object sender, SelectionChangedEventArgs e)
    {
        if (switching || Pages.SelectedItem is not PageItem next) return;
        switching = true;
        Pages.IsEnabled=false;
        await Guard(async () =>
        {
            await SaveCurrent();
            current = next; recordId = null; dirty = false;
            await LoadPage(next);
        });
        switching = false;
        Pages.IsEnabled=true;
    }

    async Task LoadPage(PageItem page)
    {
        Editor.IsEnabled=false;
        try
        {
        int version = ++generation;
        var details = await Call("details", new() { ["id"] = page.Id });
        var bookProfile=await Call("book_profile",new() { ["id"]=page.Id });
        var rendering = await Call("render", new() { ["id"] = page.Id });
        if (version != generation || current?.Id != page.Id) return;
        var bitmap = new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad; bitmap.UriSource = new Uri(rendering["path"]!.ToString()); bitmap.EndInit(); bitmap.Freeze();
        Preview.Source = bitmap; Overlay.Children.Clear();
        if(bookProfile["model"]?.ToString() is string bookModel && File.Exists(bookModel)) ModelPath.Text=bookModel;
        if(JsonNode.Parse(details["roi"]!.ToString()) is JsonArray region)
        {
            var rectangle=new Rectangle { Width=region[2]!.GetValue<double>()*bitmap.Width, Height=region[3]!.GetValue<double>()*bitmap.Height, Stroke=Brushes.DodgerBlue, StrokeThickness=3 };
            Canvas.SetLeft(rectangle,region[0]!.GetValue<double>()*bitmap.Width); Canvas.SetTop(rectangle,region[1]!.GetValue<double>()*bitmap.Height); Overlay.Children.Add(rectangle);
        }
        loading = true;
        Records.ItemsSource = details["records"]!.AsArray().Select(n => new RecordItem(n!.AsObject())).ToList();
        LineList.ItemsSource = details["lines"]!.AsArray().Select((n,i) => new LineItem(i,n!.AsObject())).ToList();
        if (Records.Items.Count > 0) { Records.SelectedIndex = 0; Fill(((RecordItem)Records.Items[0]).Data); }
        else Fill(new JsonObject { ["text"] = details["text"]!.ToString(), ["kind"] = "Інші записи та примітки" });
        loading = false;
        Status.Text = $"{page.Name} • {T("Стор.")} {page.Num+1} • {T(details["status"]!.ToString())} {T(details["error"]!.ToString())}";
        }
        finally { Editor.IsEnabled=true; }
    }

    void Fill(JsonObject data)
    {
        bool wasLoading = loading; loading = true;
        recordId = data["id"]?.ToString();
        Transcript.Text = data["text"]?.ToString() ?? "";
        Kind.SelectedIndex = Math.Max(0, Array.IndexOf(KindKeys, data["kind"]?.ToString()));
        RecordNumber.Text = data["number"]?.ToString() ?? ""; RecordDate.Text = data["date"]?.ToString() ?? "";
        Person.Text = data["person"]?.ToString() ?? ""; Related1.Text = data["related1"]?.ToString() ?? ""; Related2.Text = data["related2"]?.ToString() ?? "";
        Notes.Text = data["notes"]?.ToString() ?? ""; Place.Text = data["place"]?.ToString() ?? ""; House.Text = data["house"]?.ToString() ?? "";
        Age.Text=data["age"]?.ToString() ?? ""; Cause.Text=data["cause"]?.ToString() ?? "";
        Verified.IsChecked = data["verified"] is JsonValue v && v.TryGetValue<bool>(out bool check) && check;
        dirty = false; loading = wasLoading;
    }

    void Edited(object sender, RoutedEventArgs e) { if (!loading && current != null) dirty = true; }

    async Task SaveCurrent()
    {
        await SaveEditedLine();
        await saveLock.WaitAsync();
        try
        {
        if (current == null || !dirty) return;
        Editor.IsEnabled=false;
        var data = new JsonObject
        {
            ["id"] = recordId, ["page"] = current.Id, ["text"] = Transcript.Text, ["kind"] = KindKeys[Kind.SelectedIndex],
            ["number"] = RecordNumber.Text, ["date"] = RecordDate.Text, ["person"] = Person.Text, ["related1"] = Related1.Text, ["related2"] = Related2.Text,
            ["notes"] = Notes.Text, ["place"] = Place.Text, ["house"] = House.Text, ["verified"] = Verified.IsChecked == true
            , ["age"]=Age.Text, ["cause"]=Cause.Text
        };
        var result = await Call("save_record",data);
        recordId = result["id"]!.ToString(); dirty = false;
        data["id"]=recordId;
        var items=Records.Items.Cast<RecordItem>().ToList();
        int existing=items.FindIndex(r=>r.Data["id"]?.ToString()==recordId);
        if(existing>=0) items[existing]=new RecordItem(data); else items.Add(new RecordItem(data));
        loading=true; Records.ItemsSource=items; loading=false;
        }
        finally { Editor.IsEnabled=true; saveLock.Release(); }
    }

    async void Save(object sender, RoutedEventArgs e) => await Guard(async () => { await SaveCurrent(); if(current != null) await LoadPage(current); Status.Text = T("Запис збережено. Історію змін записано в бібліотеку."); });
    async void NewRecord(object sender, RoutedEventArgs e) => await Guard(async () => { if(current == null) return; await SaveCurrent(); Fill(new JsonObject { ["kind"] = "Інші записи та примітки" }); Records.SelectedItem = null; RecordNumber.Focus(); });
    async void SelectRecord(object sender, SelectionChangedEventArgs e)
    {
        if (loading || Records.SelectedItem is not RecordItem record) return;
        await Guard(async () => { await SaveCurrent(); Fill(record.Data); });
    }

    string PreprocessingMode => new[] { "original", "contrast", "binary", "lighting" }[Preprocessing.SelectedIndex];
    JsonObject OcrSettings() => new() { ["engine"] = ((ComboBoxItem)OcrEngine.SelectedItem).Content.ToString(), ["executable"] = OcrPath.Text, ["model"] = ModelPath.Text, ["segmentation"] = SegmentationPath.Text, ["languages"] = Languages.Text, ["useTextLayer"]=UseTextLayer.IsChecked==true, ["preprocess"] = PreprocessingMode };

    void InsertUncertain(object sender, RoutedEventArgs e)
    {
        if(current == null || sender is not Button button) return;
        Transcript.SelectedText = button.Tag.ToString()!;
        Verified.IsChecked=false; Transcript.Focus();
        Status.Text=T("Позначено невідомий текст. Відсутні літери не відновлено.");
    }

    async void PreviewProcessing(object sender, RoutedEventArgs e)
    {
        if(current == null) return;
        var id=current.Id; var mode=PreprocessingMode;
        await Guard(async () =>
        {
            var rendering=await Call("render",new() { ["id"]=id,["preprocess"]=mode });
            if(current?.Id != id) return;
            var bitmap=new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption=BitmapCacheOption.OnLoad; bitmap.UriSource=new Uri(rendering["path"]!.ToString()); bitmap.EndInit(); bitmap.Freeze(); Preview.Source=bitmap;
            Status.Text=T("Перегляд копії. Щоб повернути оригінал, виберіть «Оригінал» і натисніть перегляд. Обробка може приховати бліді штрихи.");
        });
    }

    async void ImageQuality(object sender, RoutedEventArgs e)
    {
        if(current == null) return;
        var id=current.Id;
        await Guard(async () =>
        {
            var result=await Call("image_quality",new() { ["id"]=id });
            var messages=new List<string> { F("Розмір ділянки OCR: {0} × {1}",result["width"],result["height"]) };
            foreach(var flag in result["flags"]!.AsArray()) messages.Add(T(flag!.ToString() switch {
                "small" => "Невелике зображення: дрібні штрихи можуть бути втрачені.",
                "low_contrast" => "Низький загальний контраст: перевірте блідий текст і порожні поля.",
                "dark" => "Зображення темне: перевірте тіні та освітлення.",
                _ => "Дуже світла ділянка: можливо, бліде чорнило або порожня сторінка."
            }));
            messages.Add(T("Це лише технічні підказки. Плями, розмиття, розриви й утрачені фрагменти потрібно перевірити за оригіналом. Відсутність попереджень не гарантує читабельності."));
            MessageBox.Show(this,string.Join("\n\n",messages),T("Стан зображення"));
        });
    }

    async void Recognize(object sender, RoutedEventArgs e)
    {
        if (busy || current == null) return;
        busy = true; work = new CancellationTokenSource();
        await Guard(async () =>
        {
            await SaveCurrent(); var config = OcrSettings();
            await Call("settings", new() { ["values"] = config.DeepClone() });
            // Search filtering must not silently exclude pages from a whole-book job.
            var pages=(await Call("book_page_ids",new(){["page"]=current.Id,["pending_only"]=true})).AsArray().Select(n=>n!.ToString()).ToList();
            var queue = Channel.CreateBounded<string>(workers * 2);
            int complete = 0, failed = 0;
            var consumers = Enumerable.Range(0, workers).Select(async _ =>
            {
                await foreach (var id in queue.Reader.ReadAllAsync(work.Token))
                {
                    var args = config.DeepClone().AsObject(); args["id"] = id;
                    try { await Call("recognize", args, work.Token); }
                    catch (OperationCanceledException) { throw; }
                    catch (Exception ex) { failed++; Status.Text = T("Помилка сторінки: ") + ex.Message; }
                    complete++;
                    Status.Text = F("Розпізнано {0}/{1}; помилок: {2}. Можна переглядати й редагувати документи.",complete,pages.Count,failed);
                }
            }).ToArray();
            try { foreach (var id in pages) await queue.Writer.WriteAsync(id, work.Token); }
            catch (OperationCanceledException) { }
            finally { queue.Writer.TryComplete(); }
            await Task.WhenAll(consumers);
            work.Token.ThrowIfCancellationRequested();
            await SaveCurrent(); await RefreshPages(); if(current != null) await LoadPage(current);
            Status.Text = F("Обробку завершено: {0}/{1}; помилок: {2}. Непевний текст потребує перевірки за сканом.",complete,pages.Count,failed);
        });
        await Guard(async () => { await Call("recover"); await RefreshPages(); });
        work.Dispose(); work = null; busy = false;
    }

    void Cancel(object sender, RoutedEventArgs e) => work?.Cancel();
    void EngineChanged(object sender, SelectionChangedEventArgs e) { if(OcrPath != null) OcrPath.Text = OcrEngine.SelectedIndex != 1 ? Environment.GetEnvironmentVariable("ARCHIVEREADER_KRAKEN") ?? "kraken" : "tesseract"; }
    async void ChooseModel(object sender, RoutedEventArgs e)
    {
        if(OcrEngine.SelectedIndex==3){var package=new OpenFileDialog{Filter="Paddle language package|*.json"};if(package.ShowDialog()==true)ModelPath.Text=package.FileName;return;}
        if(OcrEngine.SelectedIndex==2){var folder=new OpenFolderDialog();if(folder.ShowDialog()==true)ModelPath.Text=folder.FolderName;else return;}
        else{var d=new OpenFileDialog{Filter=T("Моделі Kraken")+"|*.mlmodel;*.safetensors"};if(d.ShowDialog()==true)ModelPath.Text=d.FileName;else return;}
        await Guard(async()=>{var info=await Call("model_inspect",new(){["model"]=ModelPath.Text});Status.Text=T("Рушій")+": "+info["engine"];if(info["missing_polish_characters"] is JsonNode missing && missing.ToString().Length>0)Status.Text+=" · "+T("Модель не підтримує польські літери")+": "+missing;});
    }
    async void ChooseLanguageModel(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        var dialog=new ModelCatalogWindow(python,Call){Owner=this};
        if(dialog.ShowDialog()!=true||dialog.SelectedModel==null)return;
        OcrEngine.SelectedIndex=dialog.SelectedEngine=="paddle"?3:0;ModelPath.Text=dialog.SelectedModel;
        await Call("settings",new(){["values"]=OcrSettings()});
        Status.Text=T("Модель розпізнавання…")+" "+System.IO.Path.GetFileName(ModelPath.Text);
    });
    void ChooseSegmentation(object sender, RoutedEventArgs e) { var d = new OpenFileDialog { Filter = T("Моделі сегментації")+"|*.mlmodel;*.safetensors" }; if(d.ShowDialog()==true) SegmentationPath.Text=d.FileName; }
    void ZoomChanged(object sender, RoutedPropertyChangedEventArgs<double> e) { if (Scale != null) Scale.ScaleX = Scale.ScaleY = e.NewValue; }
    async void Search(object sender, RoutedEventArgs e) => await Guard(async () => { await SaveCurrent(); await RefreshPages(offset:0,locateCurrent:false); });

    async void Export(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog { FileName = "ArchiveReader.xlsx", Filter = "Excel|*.xlsx|"+T("JSON (повні дані)")+"|*.json|CSV|*.csv|"+T("Текст")+"|*.txt" };
        if(dialog.ShowDialog()!=true) return;
        await Guard(async () => { await SaveCurrent(); var result=await Call("export",new() { ["path"]=dialog.FileName, ["doc"]=current?.Doc }); Status.Text=F("Експортовано записів: {0} → {1}",result["records"],dialog.FileName); });
    }

    void OpenOriginal(object sender, RoutedEventArgs e)
    {
        if(current == null) return;
        try { Process.Start(new ProcessStartInfo(current.Path) { UseShellExecute=true }); }
        catch(Exception ex) { MessageBox.Show(this,ex.Message,T("Оригінал")); }
    }

    async void SelectLine(object sender, SelectionChangedEventArgs e)
    {
        Overlay.Children.Clear();
        if(LineList.SelectedItem is not LineItem line || current == null) return;
        LineText.Text=(line.Data["corrected"] ?? line.Data["text"])?.ToString() ?? "";
        var id=current.Id;
        await Guard(async () =>
        {
            var full=await Call("render",new() { ["id"]=id,["full"]=true });
            if(current?.Id!=id || !ReferenceEquals(LineList.SelectedItem,line) || line.Data["box"] is not JsonArray box) return;
            var preview=(BitmapSource)Preview.Source;
            var roi=full["roi"] as JsonArray;
            double rw=roi?[2]?.GetValue<double>() ?? 1, rh=roi?[3]?.GetValue<double>() ?? 1;
            double ox=(roi?[0]?.GetValue<double>() ?? 0)*preview.Width, oy=(roi?[1]?.GetValue<double>() ?? 0)*preview.Height;
            double sx=preview.Width*rw/full["width"]!.GetValue<double>(), sy=preview.Height*rh/full["height"]!.GetValue<double>();
            var rect=new Rectangle { Width=box[2]!.GetValue<double>()*sx, Height=box[3]!.GetValue<double>()*sy, Stroke=Brushes.OrangeRed, StrokeThickness=3, Fill=new SolidColorBrush(Color.FromArgb(30,255,150,0)) };
            Canvas.SetLeft(rect,ox+box[0]!.GetValue<double>()*sx); Canvas.SetTop(rect,oy+box[1]!.GetValue<double>()*sy); Overlay.Children.Add(rect); CenterSelectedLine();
        });
    }

    async void SelectImageLine(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if(current == null || Preview.Source is not BitmapSource bitmap) return;
        if(RegionMode.IsChecked==true)
        {
            if(busy) return;
            regionStart=e.GetPosition(Preview); Preview.CaptureMouse(); Overlay.Children.Clear(); return;
        }
        var id=current.Id; var point=e.GetPosition(Preview);
        await Guard(async () =>
        {
            var full=await Call("render",new() { ["id"]=id,["full"]=true });
            if(current?.Id!=id) return;
            var roi=full["roi"] as JsonArray;
            double x=(point.X/bitmap.Width-(roi?[0]?.GetValue<double>() ?? 0))*full["width"]!.GetValue<double>()/(roi?[2]?.GetValue<double>() ?? 1);
            double y=(point.Y/bitmap.Height-(roi?[1]?.GetValue<double>() ?? 0))*full["height"]!.GetValue<double>()/(roi?[3]?.GetValue<double>() ?? 1);
            foreach(var line in LineList.Items.Cast<LineItem>())
            {
                if(line.Data["box"] is not JsonArray b) continue;
                double bx=b[0]!.GetValue<double>(),by=b[1]!.GetValue<double>();
                if(x>=bx && y>=by && x<=bx+b[2]!.GetValue<double>() && y<=by+b[3]!.GetValue<double>())
                {
                    LineList.SelectedItem=line; LineList.ScrollIntoView(line); break;
                }
            }
        });
    }

    Rect RegionRect(Point end)
    {
        var bitmap=(BitmapSource)Preview.Source;
        end=new Point(Math.Clamp(end.X,0,bitmap.Width),Math.Clamp(end.Y,0,bitmap.Height));
        return new Rect(regionStart!.Value,end);
    }
    void MoveRegion(object sender,System.Windows.Input.MouseEventArgs e)
    {
        if(regionStart==null) return;
        var bounds=RegionRect(e.GetPosition(Preview)); Overlay.Children.Clear();
        var rect=new Rectangle { Width=bounds.Width,Height=bounds.Height,Stroke=Brushes.DodgerBlue,StrokeThickness=3,Fill=new SolidColorBrush(Color.FromArgb(30,0,120,255)) };
        Canvas.SetLeft(rect,bounds.X); Canvas.SetTop(rect,bounds.Y); Overlay.Children.Add(rect);
    }
    async void FinishRegion(object sender,System.Windows.Input.MouseButtonEventArgs e)
    {
        if(regionStart==null || current==null) return;
        var bounds=RegionRect(e.GetPosition(Preview)); regionStart=null; Preview.ReleaseMouseCapture();
        var bitmap=(BitmapSource)Preview.Source;
        if(bounds.Width/bitmap.Width<0.005 || bounds.Height/bitmap.Height<0.005) return;
        var id=current.Id;
        await Guard(async () =>
        {
            await SaveCurrent();
            await Call("set_region",new() { ["id"]=id,["roi"]=new JsonArray(bounds.X/bitmap.Width,bounds.Y/bitmap.Height,bounds.Width/bitmap.Width,bounds.Height/bitmap.Height) });
            if(current?.Id==id) await LoadPage(current);
            Status.Text=T("Область збережено. Натисніть «OCR цієї сторінки». Оригінал не обрізано.");
        });
    }
    async void ClearRegion(object sender,RoutedEventArgs e)
    {
        if(current==null || busy) return;
        await Guard(async () => { await SaveCurrent(); await Call("set_region",new() { ["id"]=current.Id }); await LoadPage(current); Status.Text=T("Готово"); });
    }
    async void RecognizePage(object sender,RoutedEventArgs e)
    {
        if(current==null || busy) return;
        var id=current.Id; busy=true; work=new CancellationTokenSource();
        await Guard(async () =>
        {
            await SaveCurrent(); var config=OcrSettings(); config["id"]=id; config["force"]=true;
            Status.Text=T("Розпізнавання сторінки…");
            await Call("recognize",config,work.Token);
            await SaveCurrent(); await RefreshPages(); if(current?.Id==id) await LoadPage(current);
        });
        await Guard(async () => await Call("recover"));
        work.Dispose(); work=null; busy=false;
    }

    async void SaveLine(object sender, RoutedEventArgs e)
    {
        if(current == null || LineList.SelectedItem is not LineItem line) return;
        await Guard(async () => { await SaveEditedLine(true); Status.Text=T("Перевірений рядок збережено для навчального набору. Транскрипція запису редагується окремо."); });
    }

    async void Training(object sender, RoutedEventArgs e)
    {
        var dialog=new OpenFolderDialog { Title=T("Папка для навчального набору") }; if(dialog.ShowDialog()!=true) return;
        await Guard(async () => { var result=await Call("training",new() { ["path"]=dialog.FolderName }); Status.Text=F("Навчальні рядки: {0}; перевірочні: {1}. Модель не змінювалася.",result["train"],result["validation"]); });
    }

    async void Quality(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var report=await Call("quality");
        string Rate(string name) => report[name] is JsonNode value ? (value.GetValue<double>()*100).ToString("F2")+"%" : "—";
        MessageBox.Show(this,F("Перевірених рядків: {0}\nCER: {1}\nWER: {2}\nЦе статистика вибраних виправлень, а не незалежний тест точності.",report["lines"],Rate("CER"),Rate("WER")),"CER / WER");
    });

    async void TrainModel(object sender, RoutedEventArgs e)
    {
        if(busy) return;
        busy=true; work=new CancellationTokenSource();
        await Guard(async () =>
        {
            var executable=System.IO.Path.Combine(System.IO.Path.GetDirectoryName(OcrPath.Text) ?? "", "ketos.exe");
            Status.Text=T("Донавчання окремої копії. Журнал і контрольні точки зберігаються в бібліотеці.");
            var result=await Call("train_model",new() { ["model"]=ModelPath.Text,["executable"]=executable },work.Token);
            Status.Text=F("Донавчання завершено: {0}. Нову модель потрібно перевірити й вибрати вручну.",result["path"]);
        });
        work.Dispose(); work=null; busy=false;
    }

    bool closing;
    async void OpenLibrary(object sender,RoutedEventArgs e)
    {
        if(busy) return;
        await Guard(async()=>
        {
            await SaveCurrent();
            var window=new LibraryWindow(current,Call) { Owner=this }; window.ShowDialog();
            SearchText.Text="";
            await RefreshPages(window.SelectedPageId);
            if(window.SelectedPageId!=null) current=allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId) ?? current;
            if(current!=null) await LoadPage(current);
            if(window.SelectedRecordId!=null && Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SelectedRecordId) is RecordItem record)
            { loading=true; Records.SelectedItem=record; Fill(record.Data); loading=false; }
            if(window.SelectedLine is int index && index<LineList.Items.Count) { OcrLines.IsExpanded=true; LineList.SelectedIndex=index; }
            var term=window.SearchQuery.Split(' ',StringSplitOptions.RemoveEmptyEntries).FirstOrDefault();
            if(term!=null)
            {
                var comparison=System.Globalization.CultureInfo.InvariantCulture.CompareInfo;
                var options=System.Globalization.CompareOptions.IgnoreCase|System.Globalization.CompareOptions.IgnoreNonSpace;
                int start=comparison.IndexOf(Transcript.Text,term,options);
                if(start>=0) { Transcript.Focus(); Transcript.Select(start,Math.Min(term.Length,Transcript.Text.Length-start)); }
                if(window.SelectedLine==null && LineList.Items.Cast<LineItem>().FirstOrDefault(l=>comparison.IndexOf(l.Data["corrected"]?.ToString() ?? l.Data["text"]?.ToString() ?? "",term,options)>=0) is LineItem match)
                { OcrLines.IsExpanded=true; LineList.SelectedItem=match; }
            }
            if(window.SelectedRegionId!=null && current!=null)
                new WorkbenchWindow(current,Call,ModelPath.Text,window.SelectedRegionId) { Owner=this }.ShowDialog();
        });
    }
    async void OpenWorkbench(object sender,RoutedEventArgs e)
    {
        if(current==null || busy) return;
        await Guard(async()=>
        {
            await SaveCurrent();
            var window=new WorkbenchWindow(current,Call,ModelPath.Text) { Owner=this };
            window.ShowDialog();
            await RefreshPages(window.SelectedPageId);
            if(window.SelectedPageId!=null && allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId) is PageItem selected)
            { current=selected; await LoadPage(selected); }
            else if(current!=null) await LoadPage(current);
            if(window.SelectedRecordId!=null && Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SelectedRecordId) is RecordItem target)
            { loading=true; Records.SelectedItem=target; Fill(target.Data); loading=false; }
        });
    }
    async void OnClosing(object? sender, CancelEventArgs e)
    {
        if(closing) return;
        e.Cancel=true;
        try { await SaveCurrent(); work?.Cancel(); closing=true; _ = Dispatcher.BeginInvoke(new Action(Close)); }
        catch(Exception ex) { MessageBox.Show(this,T("Не вдалося зберегти зміни: ")+ex.Message,"ArchiveReader"); }
    }

    async void ChangeLanguage(object sender, SelectionChangedEventArgs e)
    {
        if(loading || InterfaceLanguage.SelectedItem is not ComboBoxItem selected) return;
        Localizer.Apply(this,selected.Tag.ToString()!);
        Pages.Items.Refresh(); Records.Items.Refresh(); Status.Text=T("Готово");
        await Guard(async () => await Call("settings",new() { ["values"]=new JsonObject { ["uiLanguage"]=Localizer.Language } }));
    }
}
